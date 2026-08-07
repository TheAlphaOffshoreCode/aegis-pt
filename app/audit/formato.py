"""Versão do formato do payload de auditoria.

Módulo próprio, sem nenhuma dependência, porque tanto o modelo quanto a escrita da trilha
precisam desta constante — e um importando o outro fecharia um ciclo.

**É um contrato congelado.** Mudar o conteúdo do payload sem subir esta versão invalida
retroativamente todos os eventos já gravados: o verificador recalcularia hashes por um formato
que não foi o usado na selagem e acusaria adulteração onde não houve. Ao acrescentar um campo,
suba a versão e mantenha o formato anterior montável.

| Versão | Mudança |
|---|---|
| 1 | formato inicial (L5) |
| 2 | acrescenta `evento_compensado_id` (L6) |
"""

VERSAO_PAYLOAD = 2
