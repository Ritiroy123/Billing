from rest_framework.test import APITestCase


class AuthTests(APITestCase):
    def test_register_login_and_me(self):
        r = self.client.post("/api/auth/register/",
                             {"username": "riya", "password": "Str0ngPass!", "role": "USER"})
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("password", r.data)          # never leak the password

        r = self.client.post("/api/auth/token/",
                             {"username": "riya", "password": "Str0ngPass!"})
        self.assertEqual(r.status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {r.data['token']}")
        r = self.client.get("/api/auth/me/")
        self.assertEqual(r.data["role"], "USER")

    def test_me_requires_token(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_provider_registration_requires_rate(self):
        r = self.client.post("/api/auth/register/",
                             {"username": "doc", "password": "Str0ngPass!", "role": "PROVIDER"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("per_minute_rate", r.data)
    
