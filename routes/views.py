from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import FindRouteRequestSerializer


class FindRouteView(APIView):
    def get(self, request):
        serializer = FindRouteRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        # TODO: implement route + fuel stop planning.
        return Response(
            {'request': serializer.validated_data, 'route': None},
            status=status.HTTP_200_OK,
        )
