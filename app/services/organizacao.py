"""Consulta da estrutura da operação: unidades, áreas e equipamentos.

Só leitura. A estrutura da unidade é cadastro, e nasce pelo seed ou pela administração — não
pela tela de emissão, que apenas escolhe entre o que já existe.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organizacao import Area
from app.models.pessoa import Usuario
from app.security.dependencias import unidades_visiveis


def listar_areas(db: Session, usuario: Usuario) -> list[Area]:
    """Áreas que o usuário alcança, ordenadas pelo código.

    Regra 5: o escopo entra na consulta. Uma lista de áreas parece inofensiva, mas os códigos
    e nomes de área de uma unidade já dizem o que existe a bordo dela.
    """
    consulta = select(Area).order_by(Area.unidade_id, Area.codigo)
    unidades = unidades_visiveis(usuario)
    if unidades is not None:
        consulta = consulta.where(Area.unidade_id.in_(unidades))
    return list(db.scalars(consulta))
