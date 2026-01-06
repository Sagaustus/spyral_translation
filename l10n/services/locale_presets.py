from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocaleSeed:
    code: str
    bcp47: str
    name: str
    script: str | None
    is_rtl: bool


PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE = "global_plus_africa_india_chinese"


LOCALE_PRESETS: dict[str, list[LocaleSeed]] = {
    PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE: [
        # Chinese variants
        LocaleSeed(
            code="zh-hans",
            bcp47="zh-Hans",
            name="Chinese (Simplified)",
            script="Hans",
            is_rtl=False,
        ),
        LocaleSeed(
            code="zh-hant",
            bcp47="zh-Hant",
            name="Chinese (Traditional)",
            script="Hant",
            is_rtl=False,
        ),
        # Indian languages
        LocaleSeed(code="ta", bcp47="ta", name="Tamil", script="Tamil", is_rtl=False),
        LocaleSeed(code="te", bcp47="te", name="Telugu", script="Telu", is_rtl=False),
        LocaleSeed(code="mr", bcp47="mr", name="Marathi", script="Deva", is_rtl=False),
        LocaleSeed(code="pa", bcp47="pa", name="Punjabi", script="Guru", is_rtl=False),
        LocaleSeed(code="kn", bcp47="kn", name="Kannada", script="Knda", is_rtl=False),
        LocaleSeed(code="ml", bcp47="ml", name="Malayalam", script="Mlym", is_rtl=False),
        LocaleSeed(code="or", bcp47="or", name="Odia", script="Orya", is_rtl=False),
        LocaleSeed(code="as", bcp47="as", name="Assamese", script="Beng", is_rtl=False),
        # African languages
        LocaleSeed(code="sw", bcp47="sw", name="Swahili", script="Latn", is_rtl=False),
        LocaleSeed(code="am", bcp47="am", name="Amharic", script="Ethi", is_rtl=False),
        LocaleSeed(code="ha", bcp47="ha", name="Hausa", script="Latn", is_rtl=False),
        LocaleSeed(code="yo", bcp47="yo", name="Yoruba", script="Latn", is_rtl=False),
        LocaleSeed(code="ig", bcp47="ig", name="Igbo", script="Latn", is_rtl=False),
        LocaleSeed(code="zu", bcp47="zu", name="isiZulu", script="Latn", is_rtl=False),
        LocaleSeed(code="xh", bcp47="xh", name="isiXhosa", script="Latn", is_rtl=False),
        LocaleSeed(code="so", bcp47="so", name="Somali", script="Latn", is_rtl=False),
        LocaleSeed(code="ti", bcp47="ti", name="Tigrinya", script="Ethi", is_rtl=False),
        LocaleSeed(code="rw", bcp47="rw", name="Kinyarwanda", script="Latn", is_rtl=False),
        LocaleSeed(code="sn", bcp47="sn", name="Shona", script="Latn", is_rtl=False),
    ]
}
