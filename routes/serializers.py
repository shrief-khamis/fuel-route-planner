from rest_framework import serializers


class FindRouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=255)
    finish = serializers.CharField(max_length=255)
