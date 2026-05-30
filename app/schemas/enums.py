"""Core enumerations for the PEMA triage engine."""

from enum import Enum





class Urgency(str, Enum):
    """Urgency classification for triage outcome (PRD §6.3)."""

    EMERGENCY = "emergency"
    URGENT = "urgent"
    ROUTINE = "routine"


class SessionStatus(str, Enum):
    """Conversation state machine states (PRD §5.3)."""

    CONSENT_FRAMING = "consent_framing"
    CHIEF_COMPLAINT = "chief_complaint"
    FACT_GATHERING = "fact_gathering"
    SPECIALTY_ROUTING = "specialty_routing"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


class MessageRole(str, Enum):
    """Who sent the message."""

    USER = "user"
    SYSTEM = "system"


class SessionMode(str, Enum):
    """Behavioral mode of the triage assistant."""

    PATIENT = "patient"
    DOCTOR = "doctor"


class Language(str, Enum):
    """Supported languages for the MVP."""

    EN = "en"
    UR = "ur"
