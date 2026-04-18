import hashlib
from openpyxl import Workbook
from datetime import timedelta
from decimal import Decimal

from common.utils import RATES, convert_to_uzs
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.accounts.models import UserRole
from api.accounts.permissions import IsAuthenticatedAndVerified
from api.loads.choices import CargoCategory, Currency, TransportType
from api.orders.models import Order

from .serializers import (
    CountryDirectionDetailSerializer,
    CountryDirectionsListResponseSerializer,
    DirectionDetailSerializer,
    GlobalAnalyticsSerializer,
    MyAnalyticsSerializer,
    PartnerAnalyticsSerializer,
)

User = get_user_model()


class BaseAnalyticsMixin:
    completed_statuses = [Order.OrderStatus.DELIVERED, Order.OrderStatus.PAID]

    @staticmethod
    def _qp_first(request, *keys: str) -> str | None:
        for key in keys:
            value = request.query_params.get(key)
            if value is not None:
                return value
        return None

    def use_global_scope(self, request) -> bool:
        raw = self._qp_first(request, "global", "is_global")
        if raw is None:
            return True
        return str(raw).strip().lower() in {"1", "true", "yes", "y", "да"}

    def scoped_completed_orders_qs(self, request):
        qs = Order.objects.filter(status__in=self.completed_statuses).select_related("cargo")
        if self.use_global_scope(request):
            request._analytics_scope = "global"
            return qs

        user = request.user
        role = getattr(user, "role", None)
        if role == UserRole.LOGISTIC:
            return qs.filter(customer=user)
        if role == UserRole.CARRIER:
            return qs.filter(carrier=user)
        return qs.filter(Q(customer=user) | Q(carrier=user))

    def normalize_cargo_category(self, value: str | None) -> str | None:
        if not value:
            return None

        raw = value.strip()
        if not raw:
            return None
        if raw.lower() in {"all", "все"}:
            return None

        allowed = {c.value for c in CargoCategory}
        if raw in allowed:
            return raw

        upper = raw.upper()
        if upper in allowed:
            return upper

        by_label = {c.label.lower(): c.value for c in CargoCategory}
        return by_label.get(raw.lower(), raw)

    def normalize_transport_type(self, value: str | None) -> str | None:
        if not value:
            return None

        raw = value.strip()
        if not raw:
            return None
        if raw.lower() in {"all", "все"}:
            return None

        allowed = {c.value for c in TransportType}
        if raw in allowed:
            return raw

        upper = raw.upper()
        if upper in allowed:
            return upper

        by_label = {c.label.lower(): c.value for c in TransportType}
        return by_label.get(raw.lower(), raw)

    def normalize_currency(self, value: str | None) -> str:
        if not value:
            return Currency.USD

        normalized = value.strip().upper()
        if normalized in RATES:
            return normalized
        return Currency.USD

    @staticmethod
    def normalize_chart_mode(value: str | None) -> str:
        if not value:
            return "shipments"

        normalized = value.strip().lower()
        if normalized in {"shipments", "transportations", "перевозки"}:
            return "shipments"
        if normalized in {"prices", "price", "цены", "стоимость"}:
            return "prices"
        return "shipments"

    def _convert_amount(
        self, amount, source_currency: str | None, target_currency: str
    ) -> float | None:
        if amount is None:
            return None

        src = (source_currency or "").upper().strip() or Currency.UZS
        if src not in RATES:
            return None
        if target_currency not in RATES:
            return None

        amount_uzs = convert_to_uzs(Decimal(amount), src)
        return float(amount_uzs / RATES[target_currency])

    def _empty_price_curve(self):
        return {
            "avg": [0.0] * 12,
            "min": [0.0] * 12,
            "max": [0.0] * 12,
        }

    def _build_pie_charts(self, qs, year: int):
        year_qs = qs.filter(created_at__year=year).select_related("cargo")
        total = year_qs.count()

        category_label_map = {c.value: c.label for c in CargoCategory}
        transport_label_map = {t.value: t.label for t in TransportType}

        category_rows = (
            year_qs.values("cargo__cargo_category")
            .annotate(shipments=Count("id"))
            .order_by("-shipments")
        )
        transport_rows = (
            year_qs.values("cargo__transport_type")
            .annotate(shipments=Count("id"))
            .order_by("-shipments")
        )

        def to_slices(rows, field_name, labels):
            result = []
            for row in rows:
                raw_value = row[field_name] or "OTHER"
                shipments = int(row["shipments"] or 0)
                percent = (shipments / total * 100.0) if total > 0 else 0.0
                result.append(
                    {
                        "value": raw_value,
                        "label": labels.get(raw_value, raw_value),
                        "shipments": shipments,
                        "percent": round(percent, 2),
                    }
                )
            return result

        return {
            "year": year,
            "total_shipments": total,
            "by_cargo_category": to_slices(
                category_rows, "cargo__cargo_category", category_label_map
            ),
            "by_transport_type": to_slices(
                transport_rows, "cargo__transport_type", transport_label_map
            ),
        }

    def _apply_seasonal_filters(self, request, qs):
        transport_type = self._qp_first(request, "transport_type", "transportType", "type")
        category = self._qp_first(request, "cargo_category", "cargoCategory", "category")

        normalized_transport = self.normalize_transport_type(transport_type)
        if normalized_transport:
            qs = qs.filter(cargo__transport_type=normalized_transport)

        normalized_category = self.normalize_cargo_category(category)
        if normalized_category:
            qs = qs.filter(cargo__cargo_category=normalized_category)

        return qs

    def _build_season_chart(self, request, qs, year: int):
        mode = self.normalize_chart_mode(
            self._qp_first(request, "mode", "metric", "chart_type", "chartType")
        )
        currency = self.normalize_currency(request.query_params.get("currency"))
        labels = [self.month_label(m) for m in range(1, 13)]

        chart_qs = self._apply_seasonal_filters(request, qs).filter(created_at__year=year)
        month_counts = {
            row["m"].month: int(row["shipments"] or 0)
            for row in chart_qs.annotate(m=TruncMonth("created_at"))
            .values("m")
            .annotate(shipments=Count("id"))
        }
        shipments = [month_counts.get(m, 0) for m in range(1, 13)]

        prices_customer_to_intermediary = [[] for _ in range(12)]
        prices_carrier_earnings = [[] for _ in range(12)]

        rows = chart_qs.values(
            "created_at",
            "logistic_id",
            "price_total",
            "currency",
            "driver_price",
            "driver_currency",
        )

        for row in rows:
            month_index = row["created_at"].month - 1

            if row["logistic_id"] and row["price_total"] is not None:
                converted_customer = self._convert_amount(
                    row["price_total"], row["currency"], currency
                )
                if converted_customer is not None:
                    prices_customer_to_intermediary[month_index].append(converted_customer)

            carrier_amount = row["driver_price"]
            carrier_currency = row["driver_currency"] or row["currency"]
            if carrier_amount is None:
                carrier_amount = row["price_total"]

            converted_carrier = self._convert_amount(carrier_amount, carrier_currency, currency)
            if converted_carrier is not None:
                prices_carrier_earnings[month_index].append(converted_carrier)

        def curve(values_by_month):
            avg = []
            min_values = []
            max_values = []
            for values in values_by_month:
                if not values:
                    avg.append(0.0)
                    min_values.append(0.0)
                    max_values.append(0.0)
                    continue

                avg.append(round(sum(values) / len(values), 2))
                min_values.append(round(min(values), 2))
                max_values.append(round(max(values), 2))
            return {"avg": avg, "min": min_values, "max": max_values}

        prices = {
            "currency": currency,
            "customer_to_intermediary": curve(prices_customer_to_intermediary),
            "carrier_earnings": curve(prices_carrier_earnings),
        }

        return {
            "mode": mode,
            "year": year,
            "labels": labels,
            "shipments": shipments,
            "prices": prices,
        }

    def month_label(self, m):
        return [
            "",
            "Янв",
            "Фев",
            "Мар",
            "Апр",
            "Май",
            "Июн",
            "Июл",
            "Авг",
            "Сен",
            "Окт",
            "Ноя",
            "Дек",
        ][m]

    def apply_filters(self, request, qs):
        date_from = self._qp_first(request, "date_from", "dateFrom")
        date_to = self._qp_first(request, "date_to", "dateTo")

        origin_region = self._qp_first(
            request,
            "origin_region",
            "originRegion",
            "origin",
            "from_region",
            "fromRegion",
            "from",
            "original_region",
            "originalRegion",
        )
        destination_region = self._qp_first(
            request,
            "destination_region",
            "destinationRegion",
            "destination",
            "to_region",
            "toRegion",
            "to",
            "target_region",
            "targetRegion",
        )

        origin_country = self._qp_first(request, "origin_country", "originCountry")

        destination_country = self._qp_first(request, "destination_country", "destinationCountry")

        transport_type = self._qp_first(request, "transport_type", "transportType", "type")
        category = self._qp_first(request, "cargo_category", "cargoCategory", "category")
        payment_method = self._qp_first(request, "payment_method", "paymentMethod")

        if date_from:
            qs = qs.filter(cargo__load_date__gte=date_from)

        if date_to:
            qs = qs.filter(cargo__delivery_date__lte=date_to)

        if origin_country:
            qs = qs.filter(cargo__origin_country__iexact=origin_country)

        if destination_country:
            qs = qs.filter(cargo__destination_country__iexact=destination_country)

        if origin_region:
            qs = qs.filter(cargo__origin_region__iexact=origin_region)

        if destination_region:
            qs = qs.filter(cargo__destination_region__iexact=destination_region)

        if transport_type:
            qs = qs.filter(cargo__transport_type=transport_type)

        if category:
            normalized_category = self.normalize_cargo_category(category)
            if normalized_category:
                qs = qs.filter(cargo__cargo_category=normalized_category)

        if payment_method:
            qs = qs.filter(cargo__payment_method=payment_method)

        return qs

    def build_directions(self, qs):
        directions_agg = (
            qs.select_related("cargo")
            .values(
                "cargo__origin_region",
                "cargo__destination_region",
            )
            .annotate(
                shipments=Count("id"),
                avg_price=Avg("cargo__price_uzs"),
                min_price=Min("cargo__price_uzs"),
                max_price=Max("cargo__price_uzs"),
                total_weight=Sum("cargo__weight_kg"),
                avg_duration=Avg(
                    ExpressionWrapper(
                        F("unloading_datetime") - F("loading_datetime"),
                        output_field=DurationField(),
                    )
                ),
            )
            .order_by("-shipments")[:10]
        )

        directions_data = []
        for d in directions_agg:
            origin = d["cargo__origin_region"] or ""
            destination = d["cargo__destination_region"] or ""

            raw = f"{origin}:{destination}"
            direction_id = hashlib.md5(raw.encode()).hexdigest()
            duration = d["avg_duration"]
            hours = duration.total_seconds() / 3600 if duration else 0

            directions_data.append(
                {
                    "id": direction_id,
                    "origin": d["cargo__origin_region"] or "—",
                    "destination": d["cargo__destination_region"] or "—",
                    "load_date": d.get("cargo__load_date"),
                    "delivery_date": d.get("cargo__delivery_date"),
                    "price_value": float(d["avg_price"] or 0),
                    "min_price": float(d["min_price"] or 0),
                    "max_price": float(d["max_price"] or 0),
                    "price_currency": "UZS",
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": round(hours, 1),
                }
            )
        return directions_data

    def build_response_data(self, request, qs, rating_value=0):
        now = timezone.now()
        summary_qs = self.apply_filters(request, qs)

        days = 30
        current_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=days * 2)

        current_qs = summary_qs.filter(created_at__gte=current_start)
        prev_qs = summary_qs.filter(created_at__gte=prev_start, created_at__lt=current_start)

        current_cnt = current_qs.count()
        prev_cnt = prev_qs.count()

        if prev_cnt > 0:
            successful_change = (current_cnt - prev_cnt) / prev_cnt
        else:
            successful_change = 1.0 if current_cnt > 0 else 0.0

        if hasattr(request, "_analytics_scope") and request._analytics_scope == "global":
            registered_since = None
            days_since_registered = None
        else:
            registered_since = getattr(request.user, "date_joined", now).date()
            days_since_registered = (now.date() - registered_since).days

        agg = summary_qs.aggregate(
            total_km=Sum("route_distance_km"),
            avg_km=Avg("route_distance_km"),
            total_weight=Sum("cargo__weight_kg"),
            min_price=Min("cargo__price_uzs"),
            max_price=Max("cargo__price_uzs"),
        )
        distance_km = float(agg["total_km"] or 0)
        avg_distance_km = float(agg["avg_km"] or 0)
        total_weight_kg = float(agg["total_weight"] or 0)
        min_price = float(agg["min_price"] or 0)
        max_price = float(agg["max_price"] or 0)

        directions_count = (
            summary_qs.values("cargo__origin_region", "cargo__destination_region")
            .distinct()
            .count()
        )
        deals_count = summary_qs.count()

        current_agg = current_qs.aggregate(
            total_price=Sum("cargo__price_uzs"),
            total_km=Sum("route_distance_km"),
        )
        prev_agg = prev_qs.aggregate(
            total_price=Sum("cargo__price_uzs"),
            total_km=Sum("route_distance_km"),
        )

        current_total_price = float(current_agg["total_price"] or 0)
        current_total_km = float(current_agg["total_km"] or 0)
        prev_total_price = float(prev_agg["total_price"] or 0)
        prev_total_km = float(prev_agg["total_km"] or 0)

        avg_price_per_km = current_total_price / current_total_km if current_total_km > 0 else 0.0
        prev_avg_price_per_km = prev_total_price / prev_total_km if prev_total_km > 0 else 0.0

        if prev_avg_price_per_km > 0:
            avg_price_per_km_change = (
                avg_price_per_km - prev_avg_price_per_km
            ) / prev_avg_price_per_km
        else:
            avg_price_per_km_change = 1.0 if avg_price_per_km > 0 else 0.0

        year = int(request.query_params.get("year", now.year))
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        directions_data = self.build_directions(summary_qs)

        data = {
            "successful_deliveries": current_cnt,
            "successful_deliveries_change": round(successful_change, 3),
            "distance_km": distance_km,
            "avg_distance_km": round(avg_distance_km, 2),
            "deals_count": deals_count,
            "directions_count": directions_count,
            "total_weight_kg": total_weight_kg,
            "min_price": min_price,
            "max_price": max_price,
            "price_currency": "UZS",
            "average_price_per_km": round(avg_price_per_km, 2),
            "average_price_per_km_change": round(avg_price_per_km_change, 3),
            "directions": directions_data,
            "pie_charts": pie_charts,
            "season_chart": season_chart,
        }

        if not (hasattr(request, "_analytics_scope") and request._analytics_scope == "global"):
            data["registered_since"] = registered_since
            data["days_since_registered"] = days_since_registered
            data["rating"] = float(rating_value or 0)

        return data

    def export_to_excel(self, data, filename="analytics.xlsx"):
        wb = Workbook()
        ws = wb.active
        ws.title = "Analytics"

        ws.append(["Метрика", "Значение"])
        ws.append(["Сделки", data["deals_count"]])
        ws.append(["Направления", data["directions_count"]])
        ws.append(["Общий вес", data["total_weight_kg"]])
        ws.append(["Мин цена", data["min_price"]])
        ws.append(["Макс цена", data["max_price"]])
        ws.append(["Средняя цена за км", data["average_price_per_km"]])

        ws.append([])

        ws.append(
            [
                "Откуда",
                "Куда",
                "Средняя цена",
                "Мин цена",
                "Макс цена",
                "Кол-во",
                "Вес",
                "Время (ч)",
            ]
        )

        for d in data["directions"]:
            ws.append(
                [
                    d["origin"],
                    d["destination"],
                    d["price_value"],
                    d["min_price"],
                    d["max_price"],
                    d["shipments"],
                    d["weight"],
                    d["time"],
                ]
            )

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        wb.save(response)
        return response


@extend_schema(responses=MyAnalyticsSerializer)
class MyAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        user = request.user
        qs = Order.objects.filter(status__in=self.completed_statuses)

        role = getattr(user, "role", None)
        if role == UserRole.LOGISTIC:
            qs = qs.filter(customer=user)
        elif role == UserRole.CARRIER:
            qs = qs.filter(carrier=user)
        else:
            qs = qs.filter(Q(customer=user) | Q(carrier=user))

        data = self.build_response_data(request, qs, rating_value=user.avg_rating)
        ser = MyAnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)


@extend_schema(responses=GlobalAnalyticsSerializer)
class GlobalAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = Order.objects.filter(status__in=self.completed_statuses)
        request._analytics_scope = "global"

        data = self.build_response_data(request, qs, rating_value=0)
        ser = GlobalAnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)


@extend_schema(responses=DirectionDetailSerializer)
class DirectionDetailView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, direction_id):
        import hashlib

        qs = self.scoped_completed_orders_qs(request)

        matched_origin = None
        matched_destination = None

        pairs = qs.values("cargo__origin_region", "cargo__destination_region").distinct()

        for pair in pairs:
            origin = pair["cargo__origin_region"] or ""
            destination = pair["cargo__destination_region"] or ""

            raw = f"{origin}:{destination}"
            current_id = hashlib.md5(raw.encode()).hexdigest()

            if current_id == direction_id:
                matched_origin = origin
                matched_destination = destination
                break

        if matched_origin is None:
            return Response({"detail": "Not found"}, status=404)

        qs = qs.filter(
            cargo__origin_region=matched_origin,
            cargo__destination_region=matched_destination,
        )

        data = qs.aggregate(
            shipments=Count("id"),
            weight=Sum("cargo__weight_kg"),
            avg_price=Avg("cargo__price_uzs"),
        )

        now = timezone.now()
        year = int(request.query_params.get("year", now.year))
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        return Response(
            {
                "id": direction_id,
                "origin_region": matched_origin,
                "destination_region": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": float(data["avg_price"] or 0),
                "price_currency": "UZS",
                "pie_charts": pie_charts,
                "season_chart": season_chart,
            }
        )


@extend_schema(responses=CountryDirectionDetailSerializer)
class CountryDirectionDetailView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, direction_id):
        import hashlib

        qs = self.scoped_completed_orders_qs(request)

        matched_origin = None
        matched_destination = None

        pairs = qs.values("cargo__origin_country", "cargo__destination_country").distinct()

        for pair in pairs:
            origin = pair["cargo__origin_country"] or ""
            destination = pair["cargo__destination_country"] or ""

            raw = f"{origin}:{destination}"
            current_id = hashlib.md5(raw.encode()).hexdigest()

            if current_id == direction_id:
                matched_origin = origin
                matched_destination = destination
                break

        if matched_origin is None:
            return Response({"detail": "Not found"}, status=404)

        qs = qs.filter(
            cargo__origin_country=matched_origin,
            cargo__destination_country=matched_destination,
        )

        data = qs.aggregate(
            shipments=Count("id"),
            weight=Sum("cargo__weight_kg"),
            avg_price=Avg("cargo__price_uzs"),
        )

        now = timezone.now()
        year = int(request.query_params.get("year", now.year))
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        return Response(
            {
                "id": direction_id,
                "origin_country": matched_origin,
                "destination_country": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": float(data["avg_price"] or 0),
                "price_currency": "UZS",
                "pie_charts": pie_charts,
                "season_chart": season_chart,
            }
        )


@extend_schema(responses=CountryDirectionsListResponseSerializer)
class CountryDirectionsListView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = self.scoped_completed_orders_qs(request)
        qs = self.apply_filters(request, qs)
        summary = qs.aggregate(
            total_weight=Sum("cargo__weight_kg"),
            avg_km=Avg("route_distance_km"),
        )
        deals_count = qs.count()
        directions_count = (
            qs.values("cargo__origin_country", "cargo__destination_country").distinct().count()
        )

        directions_agg = (
            qs.select_related("cargo")
            .values(
                "cargo__origin_country",
                "cargo__destination_country",
            )
            .annotate(
                shipments=Count("id"),
                avg_price=Avg("cargo__price_uzs"),
                total_weight=Sum("cargo__weight_kg"),
                avg_duration=Avg(
                    ExpressionWrapper(
                        F("unloading_datetime") - F("loading_datetime"),
                        output_field=DurationField(),
                    )
                ),
            )
            .order_by("-shipments")
        )

        result = []
        for d in directions_agg:
            origin = d["cargo__origin_country"] or ""
            destination = d["cargo__destination_country"] or ""
            raw = f"{origin}:{destination}"
            direction_id = hashlib.md5(raw.encode()).hexdigest()
            duration = d["avg_duration"]
            hours = duration.total_seconds() / 3600 if duration else 0
            result.append(
                {
                    "id": direction_id,
                    "origin": origin or "—",
                    "destination": destination or "—",
                    "price_value": float(d["avg_price"] or 0),
                    "price_currency": "UZS",
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": round(hours, 1),
                }
            )

        return Response(
            {
                "directions_count": directions_count,
                "deals_count": deals_count,
                "total_weight_kg": float(summary["total_weight"] or 0),
                "avg_distance_km": round(float(summary["avg_km"] or 0), 2),
                "directions": result,
            }
        )


@extend_schema(responses=PartnerAnalyticsSerializer)
class PartnerAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, partner_id):
        qs = Order.objects.filter(status__in=self.completed_statuses).filter(
            Q(customer_id=partner_id) | Q(carrier_id=partner_id)
        )

        request._analytics_scope = "global"

        data = self.build_response_data(request, qs, rating_value=0)

        partner = (
            User.objects.filter(id=partner_id)
            .values("id", "first_name", "last_name", "company_name", "photo")
            .first()
        )

        if not partner:
            return Response({"detail": "Partner not found"}, status=404)

        full_name = f"{partner.get('first_name', '')} {partner.get('last_name', '')}".strip()

        data["partner"] = {
            "id": partner["id"],
            "full_name": full_name or "",
            "company_name": partner.get("company_name") or "",
            "photo": str(partner.get("photo") or ""),
        }

        ser = PartnerAnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)


class ExportAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = self.scoped_completed_orders_qs(request)
        data = self.build_response_data(request, qs)

        return self.export_to_excel(data)


class ExportDirectionAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, direction_id):
        qs = self.scoped_completed_orders_qs(request)
        qs = self.apply_filters(request, qs)

        matched_origin = None
        matched_destination = None

        pairs = qs.values("cargo__origin_region", "cargo__destination_region").distinct()

        for pair in pairs:
            origin = pair["cargo__origin_region"] or ""
            destination = pair["cargo__destination_region"] or ""

            raw = f"{origin}:{destination}"
            current_id = hashlib.md5(raw.encode()).hexdigest()

            if current_id == direction_id:
                matched_origin = origin
                matched_destination = destination
                break

        if matched_origin is None:
            return Response({"detail": "Not found"}, status=404)

        qs = qs.filter(
            cargo__origin_region=matched_origin,
            cargo__destination_region=matched_destination,
        )

        request._analytics_scope = "global"
        data = self.build_response_data(request, qs, rating_value=0)

        filename = f"analytics_{matched_origin}_{matched_destination}.xlsx"
        return self.export_to_excel(data, filename=filename)
