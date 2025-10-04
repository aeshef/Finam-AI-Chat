"""
Клиент для работы с Finam TradeAPI
https://tradeapi.finam.ru/
"""

import os
from typing import Any, Optional

import requests


class FinamAPIClient:
    """
    Клиент для взаимодействия с Finam TradeAPI

    Документация: https://tradeapi.finam.ru/
    """

    def __init__(self, access_token: Optional[str] = None, base_url: Optional[str] = None, secret_token: Optional[str] = None) -> None:
        """
        Инициализация клиента

        Args:
            access_token: Токен доступа к API (из переменной окружения FINAM_ACCESS_TOKEN)
            base_url: Базовый URL API (по умолчанию из документации)
        """
        self.access_token = access_token or os.getenv("FINAM_ACCESS_TOKEN", "")
        self.base_url = base_url or os.getenv("FINAM_API_BASE_URL", "https://api.finam.ru")
        self.secret_token = secret_token or os.getenv("FINAM_SECRET_TOKEN", "")
        self.session = requests.Session()

        if self.access_token:
            self.session.headers.update({
                "Authorization": f"{self.access_token}",
                "Content-Type": "application/json",
            })
        elif self.secret_token:
            # Try exchange secret -> JWT
            try:
                token = self._auth_exchange(self.secret_token)
                if token:
                    self.access_token = token
                    self.session.headers.update({
                        "Authorization": f"{self.access_token}",
                        "Content-Type": "application/json",
                    })
            except Exception:
                pass

    def execute_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """
        Выполнить HTTP запрос к Finam TradeAPI

        Args:
            method: HTTP метод (GET, POST, DELETE и т.д.)
            path: Путь API (например, /v1/instruments/SBER@MISX/quotes/latest)
            **kwargs: Дополнительные параметры для requests

        Returns:
            Ответ API в виде словаря

        Raises:
            requests.HTTPError: Если запрос завершился с ошибкой
        """
        url = f"{self.base_url}{path}"

        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()

            # Если ответ пустой (например, для DELETE)
            if not response.content:
                return {"status": "success", "message": "Operation completed"}

            return response.json()

        except requests.exceptions.HTTPError as e:
            # Пытаемся извлечь детали ошибки из ответа
            error_detail = {"error": str(e), "status_code": e.response.status_code if e.response else None}

            try:
                if e.response and e.response.content:
                    error_detail["details"] = e.response.json()
            except Exception:
                error_detail["details"] = e.response.text if e.response else None

            return error_detail

        except Exception as e:
            return {"error": str(e), "type": type(e).__name__}

    # --- Auth helpers ---
    def _auth_exchange(self, secret: str) -> Optional[str]:
        """Exchange long-lived secret for short-lived JWT via AuthService.

        Path is configurable via FINAM_AUTH_PATH (default: /v1/sessions). Expects {"token": "..."}.
        """
        auth_path = os.getenv("FINAM_AUTH_PATH", "/v1/sessions")
        url = f"{self.base_url}{auth_path}"
        resp = self.session.post(url, json={"secret": secret}, timeout=15)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        token = data.get("token")
        return token

    def refresh_from_secret(self, secret: Optional[str] = None) -> dict[str, Any]:
        """Refresh JWT using provided or configured secret."""
        sec = secret or self.secret_token
        if not sec:
            return {"error": "secret_token not provided"}
        try:
            token = self._auth_exchange(sec)
            if token:
                self.access_token = token
                self.session.headers.update({"Authorization": f"{self.access_token}"})
                return {"status": "ok", "token_set": True}
            return {"error": "no token in response"}
        except Exception as e:
            return {"error": str(e)}

    # Удобные методы для частых операций

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Получить текущую котировку инструмента"""
        return self.execute_request("GET", f"/v1/instruments/{symbol}/quotes/latest")

    def get_orderbook(self, symbol: str, depth: int = 10) -> dict[str, Any]:
        """Получить биржевой стакан"""
        return self.execute_request("GET", f"/v1/instruments/{symbol}/orderbook", params={"depth": depth})

    def get_candles(
        self, symbol: str, timeframe: str = "D", start: Optional[str] = None, end: Optional[str] = None
    ) -> dict[str, Any]:
        """Получить исторические свечи"""
        params = {"timeframe": timeframe}
        if start:
            params["interval.start_time"] = start
        if end:
            params["interval.end_time"] = end
        return self.execute_request("GET", f"/v1/instruments/{symbol}/bars", params=params)

    def get_account(self, account_id: str) -> dict[str, Any]:
        """Получить информацию о счете"""
        return self.execute_request("GET", f"/v1/accounts/{account_id}")

    def get_orders(self, account_id: str) -> dict[str, Any]:
        """Получить список ордеров"""
        return self.execute_request("GET", f"/v1/accounts/{account_id}/orders")

    def get_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """Получить информацию об ордере"""
        return self.execute_request("GET", f"/v1/accounts/{account_id}/orders/{order_id}")

    def create_order(self, account_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
        """Создать новый ордер"""
        return self.execute_request("POST", f"/v1/accounts/{account_id}/orders", json=order_data)

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """Отменить ордер"""
        return self.execute_request("DELETE", f"/v1/accounts/{account_id}/orders/{order_id}")

    def get_trades(self, account_id: str, start: Optional[str] = None, end: Optional[str] = None) -> dict[str, Any]:
        """Получить историю сделок"""
        params = {}
        if start:
            params["interval.start_time"] = start
        if end:
            params["interval.end_time"] = end
        return self.execute_request("GET", f"/v1/accounts/{account_id}/trades", params=params)

    def get_positions(self, account_id: str) -> dict[str, Any]:
        """Получить открытые позиции"""
        # Позиции обычно включены в ответ get_account
        return self.execute_request("GET", f"/v1/accounts/{account_id}")

    def get_session_details(self, token: Optional[str] = None) -> dict[str, Any]:
        """Получить детали текущей сессии. Finam ожидает токен в теле запроса."""
        tok = token or self.access_token
        payload = {"token": tok} if tok else {}
        return self.execute_request("POST", "/v1/sessions/details", json=payload)
