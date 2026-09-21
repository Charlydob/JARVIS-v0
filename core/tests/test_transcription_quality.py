from jarvis_core.transcription_quality import (
    QualityDecision, TranscriptionQualityGate, likely_own_tts, repetition_ratio,
)


def test_repeated_video_ending_is_rejected_with_bad_signals() -> None:
    text = "y nos vemos en el próximo video " * 3
    result = TranscriptionQualityGate().assess(text, {
        "avg_logprob": -1.1, "max_no_speech_prob": .62,
        "max_compression_ratio": 3.2, "decoded_duration_s": 4,
        "duration_after_vad_s": .25,
    })
    assert result.decision == QualityDecision.REJECT
    assert "phrase_loop" in result.reasons
    assert "hallucination_style_ending" in result.reasons


def test_legitimate_video_phrase_is_not_blocked_on_good_audio() -> None:
    result = TranscriptionQualityGate().assess("Busca el vídeo gracias por ver", {
        "avg_logprob": -.2, "max_no_speech_prob": .02,
        "max_compression_ratio": 1.1, "decoded_duration_s": 2,
        "duration_after_vad_s": 1.8,
    })
    assert result.decision == QualityDecision.ACCEPT


def test_short_weak_fragment_is_not_accepted() -> None:
    result = TranscriptionQualityGate().assess("3 2", {
        "avg_logprob": -1.4, "max_no_speech_prob": .7,
        "max_compression_ratio": 1.2, "decoded_duration_s": 1,
        "duration_after_vad_s": .1,
    })
    assert result.decision == QualityDecision.REJECT


def test_own_tts_filter_needs_substantial_match() -> None:
    assert likely_own_tts("Recordatorio creado señor", "Recordatorio creado, señor.")
    assert not likely_own_tts("Jarvis para", "Recordatorio creado, señor.")
    assert repetition_ratio("añade también mejorar transcripción") == 0
