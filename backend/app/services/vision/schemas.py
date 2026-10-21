from pydantic import BaseModel, ConfigDict, Field


class CardExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    is_template: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=10)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=10)
