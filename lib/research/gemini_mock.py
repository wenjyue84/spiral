"""lib/research/gemini_mock.py — Mock Gemini web search for testing Phase R integration."""

import json
from typing import Optional


def gemini_web_search(query: str, search_domain: Optional[str] = None) -> str:
    """Mock Gemini web search that returns canned responses for different domains.

    Used by Phase R integration tests to avoid external API calls.

    Args:
        query: Search query text
        search_domain: Domain hint (weather, finance, tech, product, legal)

    Returns:
        JSON-formatted research summary as if from Gemini web search
    """
    # Map search domain to canned response
    responses = {
        "weather": json.dumps({
            "summary": "Weather research: Sunny conditions expected in major cities",
            "sources": [
                "https://weather.example.com/forecast",
                "https://meteo.example.org/data"
            ],
            "key_points": [
                "High pressure system moving in",
                "Temperature expected to rise 5-10 degrees",
                "Low precipitation forecast"
            ]
        }),
        "finance": json.dumps({
            "summary": "Finance market update: Tech stocks rising on AI gains",
            "sources": [
                "https://finance.example.com/markets",
                "https://bloomberg.example.com/today"
            ],
            "key_points": [
                "S&P 500 up 1.2% this week",
                "AI-related companies showing 8% average gains",
                "Fed keeps interest rates unchanged"
            ]
        }),
        "tech": json.dumps({
            "summary": "Tech news: New AI models released, security vulnerabilities patched",
            "sources": [
                "https://techcrunch.example.com/ai",
                "https://arstechnica.example.com/security"
            ],
            "key_points": [
                "Claude 4.6 model announces new capabilities",
                "Security patch released for critical CVE",
                "New developer tools simplify integration"
            ]
        }),
        "product": json.dumps({
            "summary": "Product innovation: Emerging tools for data analysis and automation",
            "sources": [
                "https://producthunt.example.com/trending",
                "https://hacker-news.example.com/newest"
            ],
            "key_points": [
                "Low-code automation platforms gaining traction",
                "Analytics tools showing higher adoption",
                "Integration APIs becoming standard"
            ]
        }),
        "legal": json.dumps({
            "summary": "Legal updates: Regulatory guidance on AI use and data privacy",
            "sources": [
                "https://law.example.com/ai-regulation",
                "https://privacy.example.gov/updates"
            ],
            "key_points": [
                "AI transparency requirements expanding",
                "Data privacy standards strengthening globally",
                "Compliance frameworks being finalized"
            ]
        }),
    }

    # Return domain-specific response or generic fallback
    domain = (search_domain or "").lower()
    if domain in responses:
        return responses[domain]

    # Generic fallback for unknown domains
    return json.dumps({
        "summary": f"Research results for query: {query}",
        "sources": [
            "https://example.com/result1",
            "https://example.com/result2"
        ],
        "key_points": [
            "Finding 1 relevant to query",
            "Finding 2 relevant to query"
        ]
    })
