// Shell do PWA: por enquanto só reporta o health check da API.

const chip = document.getElementById("conexao");
const estado = document.getElementById("estado");

function linha(rotulo, valor) {
  const div = document.createElement("div");
  div.className = "linha";
  div.innerHTML = "<dt></dt><dd></dd>";
  div.querySelector("dt").textContent = rotulo;
  div.querySelector("dd").textContent = valor;
  estado.append(div);
}

fetch("/health")
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
  .then((dados) => {
    chip.textContent = "online";
    linha("Aplicação", dados.app);
    linha("Ambiente", dados.environment);
    linha("Banco", dados.database);
  })
  .catch((erro) => {
    chip.textContent = "offline";
    chip.classList.add("falha");
    linha("Erro", erro.message);
  });
