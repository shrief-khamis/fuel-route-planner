from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class FindRouteViewTests(APITestCase):
    url = reverse('find-route')

    def test_valid_request(self):
        response = self.client.get(self.url, {'start': 'New York, NY', 'finish': 'Chicago, IL'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['request'], {'start': 'New York, NY', 'finish': 'Chicago, IL'}
        )

    def test_missing_params(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start', response.data)
        self.assertIn('finish', response.data)

    def test_post_not_allowed(self):
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
