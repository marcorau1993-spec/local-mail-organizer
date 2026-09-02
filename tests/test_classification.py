from mail_organizer.classification import (
    Category,
    ModelClassification,
    Recommendation,
    apply_safety_guards,
)


def model_result(
    category: Category, confidence: float = 0.99, important: bool = False
) -> ModelClassification:
    return ModelClassification(
        category=category,
        confidence=confidence,
        recommendation=Recommendation.ARCHIVE_REVIEW,
        reason="Conservative test reason",
        potentially_important=important,
    )


def test_protected_category_is_forced_to_keep() -> None:
    result = apply_safety_guards("1", model_result(Category.FINANCE))
    assert result.protected is True
    assert result.recommendation == Recommendation.KEEP


def test_low_confidence_is_forced_to_manual_review() -> None:
    result = apply_safety_guards("2", model_result(Category.OTHER, confidence=0.89))
    assert result.protected is True
    assert result.recommendation == Recommendation.MANUAL_REVIEW


def test_newsletter_can_only_recommend_unsubscribe_review() -> None:
    result = apply_safety_guards("3", model_result(Category.NEWSLETTER))
    assert result.protected is False
    assert result.recommendation == Recommendation.UNSUBSCRIBE_REVIEW


def test_no_destructive_recommendation_exists() -> None:
    assert "delete" not in {item.value for item in Recommendation}
