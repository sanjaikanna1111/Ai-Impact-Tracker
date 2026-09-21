import asyncio
from pydantic import BaseModel

from app.config import settings
from app.providers.gemini import GeminiProvider
from app.providers.serper import SerperProvider
from app.providers.jina import JinaProvider
from app.providers.finance import CompaniesHouseProvider, SECProvider
from app.providers.fx import FXProvider


class GeminiTestResponse(BaseModel):
    message: str


async def main():
    print("\n==============================")
    print(" AI IMPACT TRACKER API TEST")
    print("==============================")

    print("\n=== SETTINGS ===")
    print("Gemini key:", bool(settings.gemini_api_key))
    print("Gemini model:", settings.gemini_model)
    print("Serper key:", bool(settings.serper_api_key))
    print("Jina key:", bool(settings.jina_api_key))
    print(
        "Companies House key:",
        bool(settings.companies_house_api_key),
    )
    print("SEC User Agent:", settings.sec_user_agent)

    # =========================================================
    # GEMINI
    # =========================================================
    print("\n=== GEMINI PROVIDER ===")

    try:
        gemini = GeminiProvider()

        result = await gemini.structured(
            """
            Return JSON only.

            Return exactly:
            {
                "message": "GEMINI_PROVIDER_OK"
            }
            """,
            GeminiTestResponse,
        )

        if not isinstance(result, GeminiTestResponse):
            raise TypeError(f"Unexpected Gemini response type: {type(result).__name__}")

        print("PASS")
        print("Message:", result.message)

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    # =========================================================
    # SERPER
    # =========================================================
    print("\n=== SERPER PROVIDER ===")

    try:
        serper = SerperProvider()

        results = await serper.search(
            "AI healthcare patient flow software",
            num=3,
        )

        print("PASS")
        print("Results:", len(results))

        for result in results:
            print("-", result.title)
            print(" ", result.url)

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    # =========================================================
    # JINA
    # =========================================================
    print("\n=== JINA PROVIDER ===")

    try:
        jina = JinaProvider()

        page = await jina.read(
            "https://example.com"
        )

        print("PASS")
        print("Title:", page.get("title"))
        print("URL:", page.get("url"))
        print(
            "Content length:",
            len(page.get("content", "")),
        )

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    # =========================================================
    # COMPANIES HOUSE
    # =========================================================
    print("\n=== COMPANIES HOUSE ===")

    try:
        companies_house = CompaniesHouseProvider()

        result = await companies_house.search_company(
            "Tesco PLC"
        )

        if result is None:
            print("FAIL")
            print("No company returned.")

        else:
            print("PASS")
            print("Status:", result.get("status"))

            if result.get("status") == "matched":
                print(
                    "Company:",
                    result.get("company_name"),
                )
                print(
                    "Company number:",
                    result.get("company_number"),
                )
                print(
                    "Similarity:",
                    result.get("similarity"),
                )

            elif result.get("status") == "ambiguous":
                print("Possible matches:")

                for company in result.get(
                    "candidates",
                    [],
                ):
                    print(
                        "-",
                        company.get("company_name"),
                        company.get("company_number"),
                    )

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    # =========================================================
    # SEC EDGAR
    # =========================================================
    print("\n=== SEC EDGAR ===")

    try:
        sec = SECProvider()

        result = await sec.company_facts(
            "Apple Inc."
        )

        if result is None:
            print("FAIL")
            print("No SEC result returned.")

        else:
            print("PASS")
            print("Status:", result.get("status"))

            if result.get("status") == "matched":
                print(
                    "Company:",
                    result.get("company_name"),
                )
                print(
                    "Ticker:",
                    result.get("ticker"),
                )
                print(
                    "CIK:",
                    result.get("cik"),
                )

                metrics = result.get(
                    "metrics",
                    {},
                )

                for name, metric in metrics.items():
                    print()
                    print(name)

                    if metric:
                        print(
                            " Value:",
                            metric.get("value"),
                        )
                        print(
                            " FY:",
                            metric.get("fy"),
                        )
                        print(
                            " End:",
                            metric.get("end"),
                        )
                    else:
                        print(" No value found")

            else:
                print(
                    "Candidates:",
                    result.get("candidates"),
                )

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    # =========================================================
    # FRANKFURTER / BOE FX
    # =========================================================
    print("\n=== FX PROVIDER ===")

    try:
        fx = FXProvider()

        rate = await fx.rate(
            "USD",
            "GBP",
        )

        converted = await fx.convert(
            1000,
            "USD",
            "GBP",
        )

        print("PASS")
        print("USD -> GBP:", rate)
        print("$1,000 -> GBP:", converted)

    except Exception as exc:
        print("FAIL")
        print(type(exc).__name__, exc)

    print("\n==============================")
    print(" TEST COMPLETE")
    print("==============================")


if __name__ == "__main__":
    asyncio.run(main())