import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.accounts.models import UserRole
from api.accounts.permissions import IsAuthenticatedAndVerified
from api.loads.choices import CargoCategory
from api.orders.models import Order

from .serializers import DirectionDetailSerializer, GlobalAnalyticsSerializer, MyAnalyticsSerializer

User = get_user_model()


class BaseAnalyticsMixin:
    completed_statuses = [Order.OrderStatus.DELIVERED, Order.OrderStatus.PAID]

    def normalize_cargo_category(self, value: str | None) -> str | None:
        if not value:
            return None

        raw = value.strip()
        if not raw:
            return None

        allowed = {c.value for c in CargoCategory}
        if raw in allowed:
            return raw

        upper = raw.upper()
        if upper in allowed:
            return upper

        by_label = {c.label.lower(): c.value for c in CargoCategory}
        return by_label.get(raw.lower(), raw)

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
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        origin_region = request.query_params.get("origin_region")
        destination_region = request.query_params.get("destination_region")
        transport_type = request.query_params.get("transport_type")
        category = request.query_params.get("cargo_category") or request.query_params.get(
            "category"
        )
        payment_method = request.query_params.get("payment_method")
        currency = request.query_params.get("currency")

        if date_from:
            qs = qs.filter(cargo__load_date__gte=date_from)

        if date_to:
            qs = qs.filter(cargo__delivery_date__lte=date_to)

        if origin_region:
            qs = qs.filter(cargo__origin_region__iexact=origin_region)

        if destination_region:
            qs = qs.filter(cargo__destination_region__iexact=destination_region)

        if transport_type:
            qs = qs.filter(cargo__transport_type=transport_type)

        if category:
            qs = qs.filter(cargo__cargo_category=self.normalize_cargo_category(category))

        if payment_method:
            qs = qs.filter(cargo__payment_method=payment_method)

        if currency:
            qs = qs.filter(cargo__price_currency=currency)

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
                    "price_currency": "UZS",
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": round(hours, 1),
                }
            )
        return directions_data

    def build_response_data(self, request, qs, rating_value=0):
        now = timezone.now()

        days = 30
        current_start = now - timedelta(days=days)
        prev_start = now - timedelta(days=days * 2)

        current_qs = qs.filter(created_at__gte=current_start)
        prev_qs = qs.filter(created_at__gte=prev_start, created_at__lt=current_start)

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

        agg = qs.aggregate(total_km=Sum("route_distance_km"))
        distance_km = float(agg["total_km"] or 0)
        deals_count = qs.count()

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
        half = request.query_params.get("half", "1")
        months = range(1, 7) if half == "1" else range(7, 13)

        base_qs = qs.filter(
            created_at__year=year,
            created_at__month__in=months,
        )

        by_month = base_qs.annotate(m=TruncMonth("created_at")).values("m")

        def sums(month_qs):
            return {
                r["m"].month: float(r["s"] or 0)
                for r in month_qs.annotate(s=Sum("cargo__price_uzs"))
            }

        user = request.user

        if hasattr(request, "_analytics_scope") and request._analytics_scope == "global":
            given_map = sums(by_month)
            received_map = sums(by_month)
            earned_map = sums(by_month)
        else:
            given_map = sums(by_month.filter(customer=user))
            received_map = sums(by_month.filter(carrier=user))
            earned_map = sums(by_month.filter(logistic=user))

        bar_chart = {
            "labels": [self.month_label(m) for m in months],
            "given": [given_map.get(m, 0) for m in months],
            "received": [received_map.get(m, 0) for m in months],
            "earned": [earned_map.get(m, 0) for m in months],
        }

        orders_qs = qs

        in_search = orders_qs.filter(status=Order.OrderStatus.NO_DRIVER).count()
        in_process = orders_qs.filter(
            status__in=[Order.OrderStatus.PENDING, Order.OrderStatus.EN_ROUTE]
        ).count()
        successful = orders_qs.filter(status__in=self.completed_statuses).count()
        cancelled = orders_qs.exclude(
            status__in=[
                Order.OrderStatus.NO_DRIVER,
                Order.OrderStatus.PENDING,
                Order.OrderStatus.EN_ROUTE,
                *self.completed_statuses,
            ]
        ).count()

        pie_chart = {
            "in_search": in_search,
            "in_process": in_process,
            "successful": successful,
            "cancelled": cancelled,
            "total": in_search + in_process + successful + cancelled,
        }

        directions_data = self.build_directions(qs)

        data = {
            "successful_deliveries": current_cnt,
            "successful_deliveries_change": round(successful_change, 3),
            "distance_km": distance_km,
            "deals_count": deals_count,
            "average_price_per_km": round(avg_price_per_km, 2),
            "average_price_per_km_change": round(avg_price_per_km_change, 3),
            "directions": directions_data,
            "bar_chart": bar_chart,
            "pie_chart": pie_chart,
        }

        if not (hasattr(request, "_analytics_scope") and request._analytics_scope == "global"):
            data["registered_since"] = registered_since
            data["days_since_registered"] = days_since_registered
            data["rating"] = float(rating_value or 0)

        return data


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

        qs = self.apply_filters(request, qs)

        data = self.build_response_data(request, qs, rating_value=user.avg_rating)
        ser = MyAnalyticsSerializer(data=data)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)


@extend_schema(responses=GlobalAnalyticsSerializer)
class GlobalAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = Order.objects.filter(status__in=self.completed_statuses)
        qs = self.apply_filters(request, qs)
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

        qs = Order.objects.filter(
            status__in=[Order.OrderStatus.DELIVERED, Order.OrderStatus.PAID]
        ).select_related("cargo")

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

        if not matched_origin:
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
        half = request.query_params.get("half", "1")
        months = range(1, 7) if half == "1" else range(7, 13)

        by_month = (
            qs.filter(created_at__year=year, created_at__month__in=months)
            .annotate(m=TruncMonth("created_at"))
            .values("m")
            .annotate(s=Sum("cargo__price_uzs"))
        )
        month_price_map = {r["m"].month: float(r["s"] or 0) for r in by_month}
        bar_chart = {
            "labels": [self.month_label(m) for m in months],
            "given": [month_price_map.get(m, 0) for m in months],
            "received": [month_price_map.get(m, 0) for m in months],
            "earned": [month_price_map.get(m, 0) for m in months],
        }

        in_search = qs.filter(status=Order.OrderStatus.NO_DRIVER).count()
        in_process = qs.filter(
            status__in=[Order.OrderStatus.PENDING, Order.OrderStatus.EN_ROUTE]
        ).count()
        successful = qs.filter(status__in=self.completed_statuses).count()
        cancelled = qs.exclude(
            status__in=[
                Order.OrderStatus.NO_DRIVER,
                Order.OrderStatus.PENDING,
                Order.OrderStatus.EN_ROUTE,
                *self.completed_statuses,
            ]
        ).count()
        pie_chart = {
            "in_search": in_search,
            "in_process": in_process,
            "successful": successful,
            "cancelled": cancelled,
            "total": in_search + in_process + successful + cancelled,
        }

        return Response(
            {
                "id": direction_id,
                "origin_region": matched_origin,
                "destination_region": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": float(data["avg_price"] or 0),
                "price_currency": "UZS",
                "bar_chart": bar_chart,
                "pie_chart": pie_chart,
            }
        )
