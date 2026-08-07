"""Anexos da PT: gravação em disco, hash e remoção.

Duas coisas nunca vêm do cliente: o **caminho** onde o arquivo é gravado e o **hash** do
conteúdo. O nome enviado é guardado apenas como rótulo para exibição.
"""

import hashlib
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.audit.documento import hash_do_documento
from app.audit.trilha import Contexto, registrar_evento
from app.config import get_settings
from app.models.enums import EstadoPT, PerfilUsuario, TipoAnexo
from app.models.permissao import Anexo, PermissaoTrabalho
from app.models.pessoa import Usuario
from app.rules.pendencias import ConflitoDeNegocio, bloqueio

# Allowlist, e não denylist: o que não está aqui não sobe. Formatos que o navegador
# renderiza como página (`.html`, `.svg`) ficam de fora de propósito.
EXTENSOES_PERMITIDAS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

BLOCO = 64 * 1024

# Anexar é permitido enquanto a PT existe: a APR chega na análise, o relatório no
# encerramento. Arquivada, o documento está fechado.
ESTADOS_QUE_ACEITAM_ANEXO = frozenset(set(EstadoPT) - {EstadoPT.ARQUIVADA})


def _extensao_de(nome: str) -> str:
    return Path(nome).suffix.lower()


def pasta_da_pt(pt: PermissaoTrabalho) -> Path:
    """Uma pasta por PT, nomeada pelo uuid — nunca por dado que o usuário escolha."""
    return get_settings().upload_dir / pt.uuid


def caminho_absoluto(anexo: Anexo) -> Path:
    """Resolve o caminho gravado e confirma que ele não escapou da pasta de uploads.

    O caminho vem do banco e foi gerado aqui, mas a conferência fica: é barata, e o dia em que
    alguém puder influenciar esse campo, ela é a diferença entre um bug e um vazamento.
    """
    raiz = get_settings().upload_dir.resolve()
    destino = Path(anexo.caminho).resolve()
    if not destino.is_relative_to(raiz):
        raise ConflitoDeNegocio(
            [bloqueio("anexo_fora_da_area", "Caminho de anexo fora da área de uploads")]
        )
    return destino


def anexar(
    db: Session,
    pt: PermissaoTrabalho,
    arquivo: UploadFile,
    tipo: TipoAnexo,
    autor: Usuario,
    valido_ate: date | None = None,
    contexto: Contexto = Contexto(),
) -> Anexo:
    """Grava o arquivo, calcula o hash e registra o anexo na trilha."""
    if pt.estado not in ESTADOS_QUE_ACEITAM_ANEXO:
        raise ConflitoDeNegocio(
            [bloqueio("pt_arquivada", "PT arquivada não recebe anexos", campo="estado")]
        )

    extensao = _extensao_de(arquivo.filename or "")
    if extensao not in EXTENSOES_PERMITIDAS:
        raise ConflitoDeNegocio(
            [
                bloqueio(
                    "extensao_nao_permitida",
                    f"Extensão '{extensao or 'sem extensão'}' não é aceita; "
                    f"use {', '.join(sorted(EXTENSOES_PERMITIDAS))}",
                    campo="arquivo",
                )
            ]
        )

    pasta = pasta_da_pt(pt)
    pasta.mkdir(parents=True, exist_ok=True)
    # Nome gerado: o nome do cliente vira rótulo, nunca caminho.
    destino = pasta / f"{uuid4()}{extensao}"
    limite = get_settings().anexo_tamanho_maximo_mb * 1024 * 1024

    digest = hashlib.sha256()
    tamanho = 0
    try:
        with destino.open("wb") as saida:
            while bloco := arquivo.file.read(BLOCO):
                tamanho += len(bloco)
                if tamanho > limite:
                    raise ConflitoDeNegocio(
                        [
                            bloqueio(
                                "arquivo_muito_grande",
                                f"O arquivo excede {get_settings().anexo_tamanho_maximo_mb} MB",
                                campo="arquivo",
                            )
                        ]
                    )
                digest.update(bloco)
                saida.write(bloco)
    except Exception:
        # Nada de arquivo órfão em disco quando a gravação não terminou.
        destino.unlink(missing_ok=True)
        raise

    if tamanho == 0:
        destino.unlink(missing_ok=True)
        raise ConflitoDeNegocio(
            [bloqueio("arquivo_vazio", "O arquivo enviado está vazio", campo="arquivo")]
        )

    anexo = Anexo(
        pt_id=pt.id,
        tipo=tipo,
        # `Path(...).name` descarta qualquer diretório que venha no nome enviado. Ele é só
        # rótulo, mas rótulo com `../` acaba usado como caminho por alguém, algum dia.
        nome_arquivo=Path(arquivo.filename or destino.name).name,
        caminho=str(destino),
        hash_sha256=digest.hexdigest(),
        valido_ate=valido_ate,
        enviado_por_id=autor.id,
    )
    db.add(anexo)
    db.flush()

    registrar_evento(
        db,
        pt=pt,
        tipo_evento="pt.anexo.adicionado",
        ator=autor,
        hash_documento=hash_do_documento(pt),
        motivo=f"{tipo}: {anexo.nome_arquivo} ({digest.hexdigest()[:12]}…)",
        contexto=contexto,
    )
    db.commit()
    db.refresh(anexo)
    return anexo


def remover(
    db: Session,
    pt: PermissaoTrabalho,
    anexo: Anexo,
    autor: Usuario,
    contexto: Contexto = Contexto(),
) -> None:
    """Remove um anexo — só enquanto a PT é rascunho, e só pelo requisitante.

    Depois que o documento circulou, o anexo faz parte do que foi analisado: retirá-lo
    reescreveria o que as pessoas assinaram.
    """
    if pt.estado != EstadoPT.RASCUNHO:
        raise ConflitoDeNegocio(
            [
                bloqueio(
                    "anexo_nao_removivel",
                    f"PT em {pt.estado} não permite remover anexo; ele já faz parte do "
                    "documento analisado",
                    campo="estado",
                )
            ]
        )
    if autor.perfil != PerfilUsuario.ADMIN and pt.requisitante_id != autor.id:
        raise ConflitoDeNegocio(
            [bloqueio("nao_e_o_requisitante", "Só o requisitante remove anexo do rascunho")]
        )

    caminho = caminho_absoluto(anexo)
    nome, tipo, hash_arquivo = anexo.nome_arquivo, anexo.tipo, anexo.hash_sha256
    db.delete(anexo)
    db.flush()

    registrar_evento(
        db,
        pt=pt,
        tipo_evento="pt.anexo.removido",
        ator=autor,
        hash_documento=hash_do_documento(pt),
        motivo=f"{tipo}: {nome} ({hash_arquivo[:12]}…)",
        contexto=contexto,
    )
    db.commit()
    # O arquivo sai do disco só depois do commit: falhar aqui deixa um órfão, e o contrário
    # deixaria uma linha apontando para nada.
    caminho.unlink(missing_ok=True)


def apagar_pasta(pt: PermissaoTrabalho) -> None:
    """Usado em testes e limpeza; a aplicação não apaga PT."""
    shutil.rmtree(pasta_da_pt(pt), ignore_errors=True)
