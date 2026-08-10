"""Uma passagem de sincronização de alertas: `python -m app.sincronizar_alertas`.

Este arquivo é a resposta à P41. `sincronizar()` sempre foi uma função que alguém chama, sem
daemon por trás — e o que faltava para o quadro de alertas não envelhecer em silêncio era um
comando que o agendador do sistema soubesse executar.

**Por que não chamar a rota HTTP.** `POST /alertas/sincronizar` existe e continua servindo ao
botão da tela, mas ela é restrita a coordenação e OIM: um cron chamando-a precisaria de uma
credencial de serviço guardada em algum lugar do servidor, com validade, rotação e o risco de
vazar — uma conta de máquina com poder de escrita, criada para resolver agendamento. Aqui o
processo já está do lado de dentro do banco, então não há credencial nova a inventar. Escopo
não é problema: `sincronizar` ignora o escopo de quem chama de propósito, porque um alerta que
só existe quando a pessoa certa clica não é um alerta.

Idempotente, como a função que ele chama: rodar de cinco em cinco minutos não infla a urgência
de nada, e uma passagem perdida é recuperada pela seguinte.

Agendamento (a linha que faltava):

    # Linux, a cada 5 minutos
    */5 * * * * cd /srv/aegis-pt && .venv/bin/python -m app.sincronizar_alertas >> /var/log/aegis-alertas.log 2>&1

    # Windows, a cada 5 minutos
    schtasks /create /tn "AEGIS alertas" /sc minute /mo 5 /tr "C:\\srv\\aegis-pt\\.venv\\Scripts\\python.exe -m app.sincronizar_alertas"

O comando lê `AEGIS_DATABASE_URL` do mesmo `.env` da aplicação, e falha ruidosamente: exceção
não tratada vira código de saída diferente de zero, que é o que faz o agendador reclamar em
vez de o quadro parar sem ninguém notar.
"""

from app.database import SessionLocal
from app.models.tipos import agora_utc
from app.services.alertas import sincronizar


def main() -> None:
    """Roda uma passagem e imprime o que ela fez, com o momento na frente.

    A linha vai para o log do agendador, e log de cron sem carimbo de tempo não responde a
    única pergunta que se faz a ele depois: até quando isto estava rodando.
    """
    with SessionLocal() as db:
        resultado = sincronizar(db)
    print(
        f"{agora_utc():%Y-%m-%d %H:%M:%SZ} alertas — "
        f"abertos: {resultado.abertos}, escalonados: {resultado.escalonados}, "
        f"resolvidos: {resultado.resolvidos}, reabertos: {resultado.reabertos}"
    )


if __name__ == "__main__":
    main()
