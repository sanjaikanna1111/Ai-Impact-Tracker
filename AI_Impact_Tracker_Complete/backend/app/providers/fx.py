from decimal import Decimal

import httpx


class FXProvider:
    BASE = "https://api.frankfurter.dev/v2/rate"

    async def rate(
        self,
        base: str,
        quote: str = "GBP",
    ) -> Decimal | None:

        base = (base or "").upper().strip()
        quote = (quote or "GBP").upper().strip()

        if not base:
            return None

        if base == quote:
            return Decimal("1")

        url = f"{self.BASE}/{base}/{quote}"

        # Prefer Bank of England data whenever GBP is involved.
        params = (
            {"providers": "BOE"}
            if base == "GBP" or quote == "GBP"
            else None
        )

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.get(
                    url,
                    params=params,
                )

                # If the requested provider is unavailable,
                # retry using Frankfurter's default provider selection.
                if response.status_code != 200 and params:
                    response = await client.get(url)

                if response.status_code != 200:
                    return None

                data = response.json()
                rate = data.get("rate")

                if rate is None:
                    return None

                return Decimal(str(rate))

            except (httpx.HTTPError, ValueError, TypeError):
                return None

    async def convert(
        self,
        amount: float | None,
        base: str,
        quote: str = "GBP",
    ) -> float | None:

        if amount is None:
            return None

        rate = await self.rate(base, quote)

        if rate is None:
            return None

        converted = Decimal(str(amount)) * rate

        return round(float(converted), 2)