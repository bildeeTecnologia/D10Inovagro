from .models import EventTypeSetting, FieldEvent

# Ordem e aparência dos cartões do app do líder (modelo aprovado: mockup 02_app_lider_lancamento_offline).
EVENT_CARDS = {
    "rain_release": {"short": "Dispensa", "icon": "🌧", "tone": "green"},
    "overtime": {"short": "Hora extra", "icon": "⏰", "tone": "amber"},
    "daily": {"short": "Diária", "icon": "🧾", "tone": "blue"},
    "sunday": {"short": "Domingo", "icon": "📅", "tone": "purple"},
    "holiday": {"short": "Feriado", "icon": "⭐", "tone": "red"},
    "occurrence": {"short": "Ocorrência", "icon": "⚠", "tone": "green"},
    "additional_12h": {"short": "Adicional 12h", "icon": "★", "tone": "gold"},
    "advance": {"short": "Adiantamento", "icon": "💵", "tone": "blue"},
}
RUBRIC_CARD = {"icon": "＋", "tone": "gold"}


def fixed_event_types():
    labels = dict(FieldEvent.EVENT_CHOICES)
    return [(value, labels[value]) for value in EVENT_CARDS]


def blocked_event_types(tenant):
    return set(
        EventTypeSetting.objects.filter(tenant=tenant, leader_available=False).values_list("event_type", flat=True)
    )


def leader_event_cards(tenant):
    """Tipos fixos liberados para o líder, na ordem do app, com rótulo curto e ícone."""
    blocked = blocked_event_types(tenant)
    labels = dict(FieldEvent.EVENT_CHOICES)
    return [
        {"value": value, "label": labels[value], **card}
        for value, card in EVENT_CARDS.items() if value not in blocked
    ]


def released_event_types(tenant):
    return {card["value"] for card in leader_event_cards(tenant)}
