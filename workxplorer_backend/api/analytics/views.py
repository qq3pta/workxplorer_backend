import hashlib
import matplotlib.pyplot as plt
import os

from datetime import date, timedelta
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from io import BytesIO

from common.utils import RATES, convert_to_uzs
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
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


def _register_pdf_fonts():
    fonts_dir = os.path.join(settings.BASE_DIR, "fonts")

    regular_path = os.path.join(fonts_dir, "Inter-Regular.ttf")
    bold_path = os.path.join(fonts_dir, "Inter-Bold.ttf")

    if os.path.exists(regular_path) and "Inter" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Inter", regular_path))

    if os.path.exists(bold_path) and "Inter-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Inter-Bold", bold_path))


_register_pdf_fonts()


class BaseAnalyticsMixin:
    completed_statuses = [Order.OrderStatus.DELIVERED, Order.OrderStatus.PAID]

    @staticmethod
    def _qp_first(request, *keys: str) -> str | None:
        for key in keys:
            value = request.query_params.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _resolve_year(request, default_year: int) -> int:
        raw_year = request.query_params.get("year")
        if raw_year in (None, ""):
            return default_year
        try:
            return int(raw_year)
        except (TypeError, ValueError):
            return default_year

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

    def my_completed_orders_qs(self, request):
        qs = Order.objects.filter(status__in=self.completed_statuses).select_related("cargo")
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
        currency = Currency.USD
        date_from = self._parse_date(
            self._qp_first(request, "date_from", "dateFrom", "load_date", "loadDate")
        )
        date_to = self._parse_date(
            self._qp_first(request, "date_to", "dateTo", "delivery_date", "deliveryDate")
        )

        chart_qs = self._apply_seasonal_filters(request, qs)

        if date_from and date_to and date_from <= date_to:
            chart_qs = chart_qs.filter(
                cargo__load_date__gte=date_from, cargo__load_date__lte=date_to
            )
            labels, bucket_ranges = self._build_range_labels(date_from, date_to)
            shipments = [0 for _ in labels]
            prices_customer_to_intermediary = [[] for _ in labels]
            prices_carrier_earnings = [[] for _ in labels]

            rows = chart_qs.values(
                "cargo__load_date",
                "logistic_id",
                "price_total",
                "currency",
                "driver_price",
                "driver_currency",
                "cargo__price_uzs",
            )
            for row in rows:
                load_date = row["cargo__load_date"]
                if not load_date:
                    continue
                bucket_index = self._bucket_index(load_date, bucket_ranges)
                if bucket_index is None:
                    continue

                shipments[bucket_index] += 1

                customer_amount = row["price_total"]
                customer_currency = row["currency"] or Currency.UZS
                if customer_amount is None:
                    customer_amount = row["cargo__price_uzs"]
                    customer_currency = Currency.UZS

                converted_customer = self._convert_amount(
                    customer_amount,
                    customer_currency,
                    currency,
                )
                if converted_customer is not None:
                    prices_customer_to_intermediary[bucket_index].append(converted_customer)

                carrier_amount = row["driver_price"]
                carrier_currency = row["driver_currency"] or row["currency"]
                if carrier_amount is None:
                    carrier_amount = row["price_total"]
                if carrier_amount is None:
                    carrier_amount = row["cargo__price_uzs"]
                    carrier_currency = Currency.UZS

                converted_carrier = self._convert_amount(carrier_amount, carrier_currency, currency)
                if converted_carrier is not None:
                    prices_carrier_earnings[bucket_index].append(converted_carrier)
        else:
            labels = [self.month_label(m) for m in range(1, 13)]
            chart_qs = chart_qs.filter(cargo__load_date__year=year)
            month_counts = {
                row["m"].month: int(row["shipments"] or 0)
                for row in chart_qs.annotate(m=TruncMonth("cargo__load_date"))
                .values("m")
                .annotate(shipments=Count("id"))
            }
            shipments = [month_counts.get(m, 0) for m in range(1, 13)]

            prices_customer_to_intermediary = [[] for _ in range(12)]
            prices_carrier_earnings = [[] for _ in range(12)]

            rows = chart_qs.values(
                "cargo__load_date",
                "logistic_id",
                "price_total",
                "currency",
                "driver_price",
                "driver_currency",
                "cargo__price_uzs",
            )

            for row in rows:
                load_date = row["cargo__load_date"]
                if not load_date:
                    continue
                month_index = load_date.month - 1

                customer_amount = row["price_total"]
                customer_currency = row["currency"] or Currency.UZS
                if customer_amount is None:
                    customer_amount = row["cargo__price_uzs"]
                    customer_currency = Currency.UZS

                converted_customer = self._convert_amount(
                    customer_amount,
                    customer_currency,
                    currency,
                )
                if converted_customer is not None:
                    prices_customer_to_intermediary[month_index].append(converted_customer)

                carrier_amount = row["driver_price"]
                carrier_currency = row["driver_currency"] or row["currency"]
                if carrier_amount is None:
                    carrier_amount = row["price_total"]
                if carrier_amount is None:
                    carrier_amount = row["cargo__price_uzs"]
                    carrier_currency = Currency.UZS

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

    @staticmethod
    def _parse_date(raw_value: str | None) -> date | None:
        if not raw_value:
            return None
        try:
            return date.fromisoformat(str(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _month_short_ru(m: int) -> str:
        return [
            "",
            "янв",
            "фев",
            "мар",
            "апр",
            "май",
            "июн",
            "июл",
            "авг",
            "сен",
            "окт",
            "ноя",
            "дек",
        ][m]

    def _fmt_day_label(self, d: date) -> str:
        return f"{d.day} {self._month_short_ru(d.month)}"

    def _build_range_labels(
        self, date_from: date, date_to: date
    ) -> tuple[list[str], list[tuple[date, date]]]:
        total_days = (date_to - date_from).days + 1

        # Up to 45 days: one label per day.
        if total_days <= 45:
            labels: list[str] = []
            ranges: list[tuple[date, date]] = []
            current = date_from
            while current <= date_to:
                labels.append(self._fmt_day_label(current))
                ranges.append((current, current))
                current += timedelta(days=1)
            return labels, ranges

        # 46..120 days: weekly buckets.
        if total_days <= 120:
            labels = []
            ranges = []
            start = date_from
            while start <= date_to:
                end = min(start + timedelta(days=6), date_to)
                if start.month == end.month:
                    label = f"{start.day}-{end.day} {self._month_short_ru(start.month)}"
                else:
                    label = (
                        f"{start.day} {self._month_short_ru(start.month)} - "
                        f"{end.day} {self._month_short_ru(end.month)}"
                    )
                labels.append(label)
                ranges.append((start, end))
                start = end + timedelta(days=1)
            return labels, ranges

        # Long ranges: monthly buckets.
        labels = []
        ranges = []
        current = date(date_from.year, date_from.month, 1)
        while current <= date_to:
            month_start = (
                date_from
                if (current.year == date_from.year and current.month == date_from.month)
                else current
            )
            if current.month == 12:
                next_month = date(current.year + 1, 1, 1)
            else:
                next_month = date(current.year, current.month + 1, 1)
            month_end = min(next_month - timedelta(days=1), date_to)
            labels.append(f"{self._month_short_ru(current.month)} {current.year}")
            ranges.append((month_start, month_end))
            current = next_month
        return labels, ranges

    @staticmethod
    def _bucket_index(target: date, bucket_ranges: list[tuple[date, date]]) -> int | None:
        for idx, (start, end) in enumerate(bucket_ranges):
            if start <= target <= end:
                return idx
        return None

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
        currency = self._qp_first(request, "currency", "price_currency")

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

        if currency and str(currency).strip().lower() not in {"all", "все"}:
            normalized_currency = self.normalize_currency(currency)
            qs = qs.filter(currency=normalized_currency)

        return qs

    def build_directions(self, qs, currency="USD"):
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

            avg_price = self._convert_amount(d["avg_price"], "UZS", currency)
            min_price = self._convert_amount(d["min_price"], "UZS", currency)
            max_price = self._convert_amount(d["max_price"], "UZS", currency)

            directions_data.append(
                {
                    "id": direction_id,
                    "origin": d["cargo__origin_region"] or "—",
                    "destination": d["cargo__destination_region"] or "—",
                    "load_date": d.get("cargo__load_date"),
                    "delivery_date": d.get("cargo__delivery_date"),
                    "price_value": round(avg_price or 0, 2),
                    "min_price": round(min_price or 0, 2),
                    "max_price": round(max_price or 0, 2),
                    "price_currency": currency,
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": self.format_duration(duration),
                }
            )
        return directions_data

    def format_duration(self, td):
        if not td:
            return "-"

        total_seconds = int(td.total_seconds())

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        parts = []

        if days:
            parts.append(f"{days} {'день' if days == 1 else 'дня' if 2 <= days <= 4 else 'дней'}")

        if hours:
            parts.append(
                f"{hours} {'час' if hours == 1 else 'часа' if 2 <= hours <= 4 else 'часов'}"
            )

        if minutes or not parts:
            parts.append(
                f"{minutes} {'минута' if minutes == 1 else 'минуты' if 2 <= minutes <= 4 else 'минут'}"
            )

        return " ".join(parts)

    def build_response_data(self, request, qs, rating_value=0):
        now = timezone.now()
        summary_qs = self.apply_filters(request, qs)
        currency = Currency.USD

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

        min_price = self._convert_amount(agg["min_price"], "UZS", currency) or 0
        max_price = self._convert_amount(agg["max_price"], "UZS", currency) or 0

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

        current_total_price_uzs = float(current_agg["total_price"] or 0)
        current_total_km = float(current_agg["total_km"] or 0)
        prev_total_price_uzs = float(prev_agg["total_price"] or 0)
        prev_total_km = float(prev_agg["total_km"] or 0)

        current_total_price = self._convert_amount(current_total_price_uzs, "UZS", currency) or 0
        prev_total_price = self._convert_amount(prev_total_price_uzs, "UZS", currency) or 0

        avg_price_per_km = current_total_price / current_total_km if current_total_km > 0 else 0.0
        prev_avg_price_per_km = prev_total_price / prev_total_km if prev_total_km > 0 else 0.0

        if prev_avg_price_per_km > 0:
            avg_price_per_km_change = (
                avg_price_per_km - prev_avg_price_per_km
            ) / prev_avg_price_per_km
        else:
            avg_price_per_km_change = 1.0 if avg_price_per_km > 0 else 0.0

        year = int(request.query_params.get("year", now.year))
        pie_charts = self._build_pie_charts(summary_qs, year)
        season_chart = self._build_season_chart(request, summary_qs, year)

        directions_data = self.build_directions(summary_qs, currency=currency)

        data = {
            "successful_deliveries": current_cnt,
            "successful_deliveries_change": round(successful_change, 3),
            "distance_km": distance_km,
            "avg_distance_km": round(avg_distance_km, 2),
            "deals_count": deals_count,
            "directions_count": directions_count,
            "total_weight_kg": total_weight_kg,
            "min_price": round(min_price, 2),
            "max_price": round(max_price, 2),
            "price_currency": "USD",
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

    def export_to_pdf(self, data, filename="analytics.pdf"):
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=28,
            rightMargin=28,
            topMargin=24,
            bottomMargin=24,
        )

        styles = getSampleStyleSheet()

        FONT_REGULAR = "Inter" if "Inter" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
        FONT_BOLD = (
            "Inter-Bold"
            if "Inter-Bold" in pdfmetrics.getRegisteredFontNames()
            else "Helvetica-Bold"
        )

        title_style = ParagraphStyle(
            "AnalyticsTitle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=21,
            leading=26,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=4,
            alignment=0,  # слева
        )

        subtitle_style = ParagraphStyle(
            "AnalyticsSubtitle",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=0,
        )

        section_title_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontName=FONT_BOLD,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=10,
        )

        label_style = ParagraphStyle(
            "LabelStyle",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748B"),
        )

        value_style = ParagraphStyle(
            "ValueStyle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=17,
            leading=20,
            textColor=colors.HexColor("#0F172A"),
        )

        body_style = ParagraphStyle(
            "BodyStyle",
            parent=styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#334155"),
        )

        body_bold_style = ParagraphStyle(
            "BodyBoldStyle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#0F172A"),
        )

        def card(content, width=None, padding=14):
            if not isinstance(content, list):
                content = [content]

            t = Table([[content]], colWidths=[width or doc.width])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
                        ("LEFTPADDING", (0, 0), (-1, -1), padding),
                        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                        ("TOPPADDING", (0, 0), (-1, -1), padding),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            return t

        def kpi_card(label, value):
            t = Table(
                [
                    [Paragraph(label, label_style)],
                    [Paragraph(str(value), value_style)],
                ],
                colWidths=[doc.width / 4 - 8],
                rowHeights=[20, 28],
            )
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 12),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            return t

        elements = []

        # Header
        elements.append(
            card(
                [
                    Paragraph("Аналитика перевозок", title_style),
                    Paragraph(
                        "Сводный отчет по перевозкам, стоимости и структуре грузов", subtitle_style
                    ),
                ],
                padding=18,
            )
        )
        elements.append(Spacer(1, 14))

        # KPI row
        kpi_table = Table(
            [
                [
                    kpi_card("Сделки", data["deals_count"]),
                    kpi_card("Направления", data["directions_count"]),
                    kpi_card("Мин. цена", f'{data["min_price"]} $'),
                    kpi_card("Макс. цена", f'{data["max_price"]} $'),
                ]
            ],
            colWidths=[doc.width / 4] * 4,
        )
        kpi_table.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(kpi_table)
        elements.append(Spacer(1, 14))

        # Summary card
        summary_rows = [
            [
                Paragraph("Общий вес", body_style),
                Paragraph(f"{data['total_weight_kg'] / 1000:,.2f} т", body_bold_style),
            ],
            [
                Paragraph("Средняя дистанция", body_style),
                Paragraph(f"{data['avg_distance_km']} км", body_bold_style),
            ],
            [
                Paragraph("Средняя цена за км", body_style),
                Paragraph(f"{data['average_price_per_km']} $", body_bold_style),
            ],
        ]

        summary_table = Table(summary_rows, colWidths=[doc.width * 0.58, doc.width * 0.28])
        summary_table.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -2), 0.6, colors.HexColor("#E2E8F0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )

        elements.append(
            card(
                [
                    Paragraph("Краткая сводка", section_title_style),
                    summary_table,
                ],
                padding=16,
            )
        )
        elements.append(Spacer(1, 14))

        # Line chart card
        line_chart = self._generate_line_chart(data["season_chart"])
        elements.append(
            card(
                [
                    Paragraph("Динамика перевозок", section_title_style),
                    Spacer(1, 4),
                    Image(line_chart, width=doc.width - 32, height=235),
                ],
                padding=16,
            )
        )
        elements.append(Spacer(1, 14))

        # Divider
        elements.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#E2E8F0")))
        elements.append(Spacer(1, 14))

        # Pie chart card
        pie_chart = self._generate_pie_chart(data["pie_charts"]["by_cargo_category"])
        elements.append(
            card(
                [
                    Paragraph("Категории грузов", section_title_style),
                    Spacer(1, 4),
                    Image(pie_chart, width=doc.width - 52, height=300),
                ],
                padding=16,
            )
        )

        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def _generate_line_chart(self, season_chart):
        buffer = BytesIO()

        labels = season_chart["labels"]
        values = season_chart["shipments"]

        plt.figure(figsize=(8.2, 4.2), dpi=160)
        ax = plt.gca()
        ax.set_facecolor("#F8FAFC")

        x = list(range(len(labels)))

        plt.plot(
            x,
            values,
            linewidth=2.8,
            marker="o",
            markersize=5,
        )
        plt.fill_between(x, values, alpha=0.12)

        plt.grid(True, linestyle="--", alpha=0.18)
        plt.title("Перевозки по периодам", fontsize=13, fontweight="bold")
        plt.xticks(x, labels, rotation=30, ha="right", fontsize=8)
        plt.yticks(fontsize=8)

        for spine in ax.spines.values():
            spine.set_visible(False)

        plt.tight_layout()
        plt.savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
        plt.close()

        buffer.seek(0)
        return buffer

    def _generate_pie_chart(self, pie_data):
        buffer = BytesIO()

        labels = [x["label"] for x in pie_data if x["shipments"] > 0]
        values = [x["shipments"] for x in pie_data if x["shipments"] > 0]

        plt.figure(figsize=(7, 5.2), dpi=160)

        if values:
            plt.pie(
                values,
                labels=labels,
                autopct="%1.1f%%",
                startangle=135,
                wedgeprops={"linewidth": 1.2, "edgecolor": "white"},
                textprops={"fontsize": 8},
                pctdistance=0.75,
                labeldistance=1.08,
            )
        else:
            plt.text(0.5, 0.5, "Нет данных", ha="center", va="center", fontsize=12)
            plt.axis("off")

        plt.title("Структура грузов", fontsize=13, fontweight="bold")
        plt.tight_layout()
        plt.savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
        plt.close()

        buffer.seek(0)
        return buffer


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
        qs = self.apply_filters(request, qs)

        data = qs.aggregate(
            shipments=Count("id"),
            weight=Sum("cargo__weight_kg"),
            avg_price=Avg("cargo__price_uzs"),
        )
        price_value = self._convert_amount(data["avg_price"], "UZS", Currency.USD) or 0

        year = self._resolve_year(request, default_year=2026)
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        return Response(
            {
                "id": direction_id,
                "origin_region": matched_origin,
                "destination_region": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": round(price_value, 2),
                "price_currency": "USD",
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
        qs = self.apply_filters(request, qs)

        data = qs.aggregate(
            shipments=Count("id"),
            weight=Sum("cargo__weight_kg"),
            avg_price=Avg("cargo__price_uzs"),
        )
        price_value = self._convert_amount(data["avg_price"], "UZS", Currency.USD) or 0

        year = self._resolve_year(request, default_year=2026)
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        return Response(
            {
                "id": direction_id,
                "origin_country": matched_origin,
                "destination_country": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": round(price_value, 2),
                "price_currency": "USD",
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

        currency = Currency.USD

        summary = qs.aggregate(
            total_weight=Sum("cargo__weight_kg"),
            avg_km=Avg("route_distance_km"),
        )
        deals_count = qs.count()
        directions_count = (
            qs.values("cargo__origin_region", "cargo__destination_region").distinct().count()
        )

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
            .order_by("-shipments")
        )

        result = []
        for d in directions_agg:
            origin = d["cargo__origin_region"] or ""
            destination = d["cargo__destination_region"] or ""
            raw = f"{origin}:{destination}"
            direction_id = hashlib.md5(raw.encode()).hexdigest()
            duration = d["avg_duration"]

            converted_price = self._convert_amount(
                d["avg_price"],
                "UZS",
                currency,
            )
            converted_min_price = self._convert_amount(
                d["min_price"],
                "UZS",
                currency,
            )
            converted_max_price = self._convert_amount(
                d["max_price"],
                "UZS",
                currency,
            )

            result.append(
                {
                    "id": direction_id,
                    "origin": origin or "—",
                    "destination": destination or "—",
                    "price_value": round(converted_price or 0, 2),
                    "min_price": round(converted_min_price or 0, 2),
                    "max_price": round(converted_max_price or 0, 2),
                    "price_currency": currency,
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": self.format_duration(duration),
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


@extend_schema(responses=CountryDirectionDetailSerializer)
class MyCountryDirectionDetailView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, direction_id):
        qs = self.my_completed_orders_qs(request)

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
        qs = self.apply_filters(request, qs)

        data = qs.aggregate(
            shipments=Count("id"),
            weight=Sum("cargo__weight_kg"),
            avg_price=Avg("cargo__price_uzs"),
        )
        price_value = self._convert_amount(data["avg_price"], "UZS", Currency.USD) or 0

        year = self._resolve_year(request, default_year=2026)
        pie_charts = self._build_pie_charts(qs, year)
        season_chart = self._build_season_chart(request, qs, year)

        return Response(
            {
                "id": direction_id,
                "origin_country": matched_origin,
                "destination_country": matched_destination,
                "shipments": data["shipments"] or 0,
                "weight": float(data["weight"] or 0),
                "price_value": round(price_value, 2),
                "price_currency": "USD",
                "pie_charts": pie_charts,
                "season_chart": season_chart,
            }
        )


@extend_schema(responses=CountryDirectionsListResponseSerializer)
class MyCountryDirectionsListView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = self.my_completed_orders_qs(request)
        qs = self.apply_filters(request, qs)

        currency = Currency.USD

        summary = qs.aggregate(
            total_weight=Sum("cargo__weight_kg"),
            avg_km=Avg("route_distance_km"),
        )
        deals_count = qs.count()
        directions_count = (
            qs.values("cargo__origin_region", "cargo__destination_region").distinct().count()
        )

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
            .order_by("-shipments")
        )

        result = []
        for d in directions_agg:
            origin = d["cargo__origin_region"] or ""
            destination = d["cargo__destination_region"] or ""
            raw = f"{origin}:{destination}"
            direction_id = hashlib.md5(raw.encode()).hexdigest()
            duration = d["avg_duration"]

            converted_price = self._convert_amount(
                d["avg_price"],
                "UZS",
                currency,
            )
            converted_min_price = self._convert_amount(
                d["min_price"],
                "UZS",
                currency,
            )
            converted_max_price = self._convert_amount(
                d["max_price"],
                "UZS",
                currency,
            )

            result.append(
                {
                    "id": direction_id,
                    "origin": origin or "—",
                    "destination": destination or "—",
                    "price_value": round(converted_price or 0, 2),
                    "min_price": round(converted_min_price or 0, 2),
                    "max_price": round(converted_max_price or 0, 2),
                    "price_currency": currency,
                    "shipments": d["shipments"],
                    "weight": float(d["total_weight"] or 0),
                    "time": self.format_duration(duration),
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
        return self.export_to_pdf(data)


class ExportMyAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request):
        qs = Order.objects.filter(status__in=self.completed_statuses).select_related("cargo")

        user = request.user
        role = getattr(user, "role", None)
        if role == UserRole.LOGISTIC:
            qs = qs.filter(customer=user)
        elif role == UserRole.CARRIER:
            qs = qs.filter(carrier=user)
        else:
            qs = qs.filter(Q(customer=user) | Q(carrier=user))

        data = self.build_response_data(request, qs, rating_value=user.avg_rating)
        return self.export_to_pdf(data, filename="my_analytics.pdf")


@extend_schema(
    operation_id="analytics_export_my_direction_file",
    responses={200: OpenApiTypes.BINARY},
)
class ExportMyDirectionAnalyticsView(BaseAnalyticsMixin, APIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, direction_id):
        qs = Order.objects.filter(status__in=self.completed_statuses).select_related("cargo")

        user = request.user
        role = getattr(user, "role", None)
        if role == UserRole.LOGISTIC:
            qs = qs.filter(customer=user)
        elif role == UserRole.CARRIER:
            qs = qs.filter(carrier=user)
        else:
            qs = qs.filter(Q(customer=user) | Q(carrier=user))

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

        data = self.build_response_data(request, qs, rating_value=user.avg_rating)

        safe_origin = (matched_origin or "origin").replace("/", "_").replace("\\", "_").strip()
        safe_destination = (
            (matched_destination or "destination").replace("/", "_").replace("\\", "_").strip()
        )
        filename = f"my_analytics_{safe_origin}_{safe_destination}.pdf"
        return self.export_to_pdf(data, filename=filename)


@extend_schema(
    operation_id="analytics_export_direction_file",
    responses={200: OpenApiTypes.BINARY},
)
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

        safe_origin = (matched_origin or "origin").replace("/", "_").replace("\\", "_").strip()
        safe_destination = (
            (matched_destination or "destination").replace("/", "_").replace("\\", "_").strip()
        )
        filename = f"analytics_{safe_origin}_{safe_destination}.pdf"
        return self.export_to_pdf(data, filename=filename)
