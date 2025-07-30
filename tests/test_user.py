import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app, get_member_email
from pydantic import EmailStr
import bcrypt
import mysql.connector
from fastapi import HTTPException
import json

class TestUser(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.mock_cursor = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cursor
        self.mock_cnxpool = MagicMock()
        self.mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        # 重置模擬狀態
        self.mock_cursor.reset_mock()
        self.mock_conn.reset_mock()
        self.mock_cnxpool.reset_mock()

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_success(self, mock_cnxpool):
        # 模擬資料庫行為
        mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_cursor.fetchone.side_effect = [None, None]  # Email 和 name 未被使用
        self.mock_cursor.lastrowid = 1

        # 模擬 bcrypt 和 JWT 行為
        with patch('app.bcrypt.gensalt', return_value=b'salt'):
            with patch('app.bcrypt.hashpw', return_value=b'hashed_password'):
                with patch('app.create_access_token', return_value='mock_token'):
                    response = self.client.post(
                        "/api/user/register",
                        json={
                            "name": "TestUser",
                            "email": "test@example.com",
                            "password": "password123",
                            "confirm_password": "password123",
                            "phone": "0912345678",
                            "city": "Taipei",
                            "favorite_teams": ["TeamA", "TeamB"]
                        }
                    )

        # debug：print 模擬調用
        # print(f"execute calls: {self.mock_cursor.execute.mock_calls}")
        # print(f"fetchone calls: {self.mock_cursor.fetchone.mock_calls}")

        # 驗證回應
        self.assertEqual(response.status_code, 200, msg=f"Failed with response: {response.json()}")
        self.assertEqual(response.json(), {"access_token": "mock_token", "token_type": "bearer"})

        # 驗證資料庫操作
        self.mock_cursor.execute.assert_any_call(
            "SELECT id FROM members WHERE email = %s", ("test@example.com",)
        )
        self.mock_cursor.execute.assert_any_call(
            "SELECT id FROM members WHERE name = %s", ("TestUser",)
        )
        self.mock_cursor.execute.assert_any_call(
            """
                    INSERT INTO members
                    (name, email, password_hash, phone, city, favorite_teams)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
            ("TestUser", "test@example.com", "hashed_password", "0912345678", "Taipei", '["TeamA", "TeamB"]')
        )
        self.mock_conn.commit.assert_called_once()

        # 驗證 fetchone 調用次數
        self.assertEqual(self.mock_cursor.fetchone.call_count, 2, 
                         msg=f"fetchone call count: {self.mock_cursor.fetchone.call_count}")

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_email_exists(self, mock_cnxpool):
        mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_cursor.fetchone.side_effect = [{"id": 1}, None]

        response = self.client.post(
            "/api/user/register",
            json={
                "name": "TestUser",
                "email": "test@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "phone": "0912345678",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "此電子郵件已被註冊"})

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_password_mismatch(self, mock_cnxpool):
        response = self.client.post(
            "/api/user/register",
            json={
                "name": "TestUser",
                "email": "test@example.com",
                "password": "password123",
                "confirm_password": "different_password",
                "phone": "0912345678",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "密碼與確認密碼不符"})

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_invalid_phone(self, mock_cnxpool):
        response = self.client.post(
            "/api/user/register",
            json={
                "name": "TestUser",
                "email": "test@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "phone": "1234567890",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("String should match pattern '^09\\d{8}$'", response.json()["detail"][0]["msg"])

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_empty_name(self, mock_cnxpool):
        response = self.client.post(
            "/api/user/register",
            json={
                "name": "",
                "email": "test@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "phone": "0912345678",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("String should have at least 1 character", response.json()["detail"][0]["msg"])

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_max_length_name(self, mock_cnxpool):
        max_name = "A" * 50
        mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_cursor.fetchone.side_effect = [None, None]
        self.mock_cursor.lastrowid = 1

        with patch('app.bcrypt.gensalt', return_value=b'salt'):
            with patch('app.bcrypt.hashpw', return_value=b'hashed_password'):
                with patch('app.create_access_token', return_value='mock_token'):
                    response = self.client.post(
                        "/api/user/register",
                        json={
                            "name": max_name,
                            "email": "test@example.com",
                            "password": "password123",
                            "confirm_password": "password123",
                            "phone": "0912345678",
                            "city": "Taipei",
                            "favorite_teams": ["TeamA", "TeamB"]
                        }
                    )

        print(f"execute calls: {self.mock_cursor.execute.mock_calls}")
        print(f"fetchone calls: {self.mock_cursor.fetchone.mock_calls}")

        self.assertEqual(response.status_code, 200, msg=f"Failed with response: {response.json()}")
        self.assertEqual(response.json(), {"access_token": "mock_token", "token_type": "bearer"})

        self.mock_cursor.execute.assert_any_call(
            "SELECT id FROM members WHERE email = %s", ("test@example.com",)
        )
        self.mock_cursor.execute.assert_any_call(
            "SELECT id FROM members WHERE name = %s", (max_name,)
        )
        self.mock_cursor.execute.assert_any_call(
            """
                    INSERT INTO members
                    (name, email, password_hash, phone, city, favorite_teams)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
            (max_name, "test@example.com", "hashed_password", "0912345678", "Taipei", '["TeamA", "TeamB"]')
        )
        self.mock_conn.commit.assert_called_once()

        self.assertEqual(self.mock_cursor.fetchone.call_count, 2, 
                         msg=f"fetchone call count: {self.mock_cursor.fetchone.call_count}")

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_short_password(self, mock_cnxpool):
        response = self.client.post(
            "/api/user/register",
            json={
                "name": "TestUser",
                "email": "test@example.com",
                "password": "short",
                "confirm_password": "short",
                "phone": "0912345678",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("String should have at least 6 characters", response.json()["detail"][0]["msg"])

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_user_register_invalid_email(self, mock_cnxpool):
        response = self.client.post(
            "/api/user/register",
            json={
                "name": "TestUser",
                "email": "invalid_email",
                "password": "password123",
                "confirm_password": "password123",
                "phone": "0912345678",
                "city": "Taipei",
                "favorite_teams": ["TeamA", "TeamB"]
            }
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("value is not a valid email address", response.json()["detail"][0]["msg"])

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_get_member_email_success(self, mock_cnxpool):
        mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_cursor.fetchone.return_value = {"email": "test@example.com"}

        result = get_member_email(self.mock_cursor, 1)

        self.assertEqual(result, "test@example.com")
        self.mock_cursor.execute.assert_called_once_with(
            "SELECT email FROM members WHERE id = %s", (1,)
        )

    @patch('app.cnxpool', new_callable=MagicMock)
    def test_get_member_email_not_found(self, mock_cnxpool):
        mock_cnxpool.get_connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_cursor.fetchone.return_value = None

        with self.assertRaises(HTTPException) as cm:
            get_member_email(self.mock_cursor, 999)

        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(cm.exception.detail, "會員 ID 999 不存在")
        self.mock_cursor.execute.assert_called_once_with(
            "SELECT email FROM members WHERE id = %s", (999,)
        )

if __name__ == '__main__':
    unittest.main()