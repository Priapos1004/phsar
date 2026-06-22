from pydantic import BaseModel


class GenreOut(BaseModel):
    """A genre name paired with its human-readable description, used by the
    frontend to render explanatory tooltips on genre badges."""

    name: str
    description: str | None = None
