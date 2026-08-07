"""Base dos schemas de leitura."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMSchema(BaseModel):
    """Schema lido diretamente de uma instância do ORM."""

    model_config = ConfigDict(from_attributes=True)


class ORMDatado(ORMSchema):
    """Schema de leitura de entidade com timestamps."""

    criado_em: datetime
    atualizado_em: datetime
