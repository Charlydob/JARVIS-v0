from jarvis_core.language import SessionLanguagePolicy


def test_ten_turn_session_resists_weak_detections_and_switches_on_clear_speech() -> None:
    policy = SessionLanguagePolicy()
    conversation = "mixed-session"
    turns = [
        ("Hola, ¿cómo estás hoy, Jarvis?", "es", .99, "es"),
        ("Quiero beber water pero seguimos hablando español.", "en", .52, "es"),
        ("Kiero saver ke tenemos para esta tarde.", "da", .91, "es"),
        ("Todo sigue bien y quiero una respuesta breve.", "es", .99, "es"),
        ("I am speaking clearly in English now and I want your answer in the same language.", "en", .99, "en"),
        ("Yes, please.", "en", .99, "en"),
        ("Water", "pt", .99, "en"),
        ("Ahora vuelvo a hablar claramente en español y quiero que me respondas así.", "es", .99, "es"),
        ("Vale, perfecto.", "pt", .99, "es"),
        ("Seguimos en español aunque diga software al final.", "en", .54, "es"),
    ]
    assert [
        policy.resolve(conversation, text, language, confidence)
        for text, language, confidence, _ in turns
    ] == [expected for *_, expected in turns]


def test_two_consistent_medium_turns_switch_language() -> None:
    policy = SessionLanguagePolicy()
    assert policy.resolve("de", "Heute Aufgaben gemeinsam planen", "de", .90) == "es"
    assert policy.resolve("de", "Morgen Termine gemeinsam planen", "de", .90) == "de"


def test_explicit_request_switches_immediately() -> None:
    policy = SessionLanguagePolicy()
    assert policy.resolve("explicit", "Por favor, responde en inglés.", "es", .99) == "en"
