from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from matching.engine import resolve, substitutes
from pharmacies.models import Availability, StockItem

from .serializers import MedicineSerializer, SearchResultSerializer


@extend_schema(
    summary="Search for a medicine near a location",
    parameters=[
        OpenApiParameter("q", str, required=True,
                         description="Brand or generic name, free text"),
        OpenApiParameter("lat", float, required=True),
        OpenApiParameter("lng", float, required=True),
        OpenApiParameter("radius", int, description="Metres, 500-50000"),
        OpenApiParameter("substitutes", bool,
                         description="Include interchangeable products"),
    ],
    responses={200: None},
)
class SearchView(APIView):
    """GET /api/v1/search?q=panadol&lat=7.2906&lng=80.6337&radius=5000

    Resolves the text to a medicine, then returns nearby pharmacies that
    hold it or an interchangeable product, nearest first.
    """

    permission_classes = [AllowAny]  # patients search before signing in

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response(
                {"detail": "Query parameter 'q' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat = float(request.query_params["lat"])
            lng = float(request.query_params["lng"])
        except (KeyError, ValueError):
            return Response(
                {"detail": "Valid 'lat' and 'lng' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return Response(
                {"detail": "Coordinates out of range."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            radius = int(request.query_params.get(
                "radius", settings.DEFAULT_SEARCH_RADIUS_M))
        except ValueError:
            radius = settings.DEFAULT_SEARCH_RADIUS_M
        radius = max(500, min(radius, 50_000))

        include_substitutes = (
            request.query_params.get("substitutes", "true").lower() != "false"
        )

        # 1. What did the user mean?
        resolution = resolve(q)
        if resolution.medicine is None:
            return Response({
                "query": q,
                "resolved": None,
                "match_method": resolution.method,
                "match_score": round(resolution.score, 1),
                "candidates": MedicineSerializer(
                    [m for m, _ in resolution.candidates], many=True
                ).data,
                "results": [],
                "detail": "Could not identify that medicine. Pick one of the "
                          "candidates or check the spelling.",
            }, status=status.HTTP_200_OK)

        wanted = resolution.medicine

        # 2. Which products would satisfy them?
        options = [wanted]
        if include_substitutes:
            options += list(substitutes(wanted))

        # 3. Who nearby has one, in stock?
        point = Point(lng, lat, srid=4326)
        results = (
            StockItem.objects
            .filter(
                medicine__in=options,
                availability__in=[Availability.IN_STOCK, Availability.LOW],
                pharmacy__is_verified=True,
                pharmacy__location__distance_lte=(point, radius),
            )
            .select_related("pharmacy", "medicine")
            .prefetch_related("medicine__medicine_ingredients__ingredient")
            .annotate(distance=Distance("pharmacy__location", point))
            .order_by("distance")[:50]
        )

        serializer = SearchResultSerializer(
            results, many=True, context={"requested_medicine_id": wanted.id}
        )

        return Response({
            "query": q,
            "resolved": MedicineSerializer(wanted).data,
            "match_method": resolution.method,
            "match_score": round(resolution.score, 1),
            "radius_m": radius,
            "result_count": len(serializer.data),
            "results": serializer.data,
            "disclaimer": "Substitutes share the same active ingredient, "
                          "strength and dosage form. Confirm with the "
                          "dispensing pharmacist before purchase.",
        })