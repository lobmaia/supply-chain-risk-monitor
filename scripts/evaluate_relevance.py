from datetime import datetime, timezone

from app.core.config import Settings
from app.models.article import Article
from app.services.processing import score_article_relevance

LABELED_SAMPLE = [
    {
        "title": "Port strike causes supply chain delays for auto parts",
        "summary": "Dockworkers walk out and shipments are delayed.",
        "normalized_content": "Port strike causes supply chain delays for auto parts shipments.",
        "expected": True,
    },
    {
        "title": "Intel says Panama Canal congestion is delaying chip shipments",
        "summary": "Semiconductor lead times are rising.",
        "normalized_content": "Intel says Panama Canal congestion is delaying chip shipments.",
        "expected": True,
    },
    {
        "title": "Celebrity chef opens new restaurant",
        "summary": "Entertainment coverage from a gala event.",
        "normalized_content": "Celebrity chef opens a new restaurant after an entertainment gala.",
        "expected": False,
    },
    {
        "title": "Retailer beats earnings expectations",
        "summary": "Quarterly profits improved despite marketing costs.",
        "normalized_content": "Retailer beats earnings expectations after strong holiday sales.",
        "expected": False,
    },
]


def build_article(sample: dict[str, str | bool]) -> Article:
    return Article(
        source_name="evaluation",
        title=str(sample["title"]),
        url=f"https://example.com/{hash(sample['title'])}",
        published_at=datetime.now(timezone.utc),
        summary=str(sample["summary"]),
        normalized_content=str(sample["normalized_content"]),
        content_hash=str(hash(sample["normalized_content"])),
    )


def main() -> None:
    settings = Settings(ingestion_enabled=False)
    tp = fp = tn = fn = 0

    for sample in LABELED_SAMPLE:
        article = build_article(sample)
        score, reasons = score_article_relevance(article, threshold=settings.relevance_threshold)
        predicted = score >= settings.relevance_threshold
        expected = bool(sample["expected"])

        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and expected:
            fn += 1
        else:
            tn += 1

        print(
            f"title={sample['title']!r} expected={expected} predicted={predicted} "
            f"score={score:.3f} reasons={reasons}"
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    accuracy = (tp + tn) / len(LABELED_SAMPLE)

    print("---")
    print(f"precision={precision:.3f}")
    print(f"recall={recall:.3f}")
    print(f"accuracy={accuracy:.3f}")


if __name__ == "__main__":
    main()
