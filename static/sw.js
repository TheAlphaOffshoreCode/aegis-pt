/* Service worker do AEGIS PT.
 *
 * Duas estratégias, escolhidas pelo que o erro custa:
 *
 * - O **shell** (HTML, CSS, JS, fontes, ícones) é cache-first. Ele muda quando a versão muda,
 *   e servir do cache é o que faz o aplicativo abrir sem sinal.
 * - Os **dados** (`/pts`, `/indicadores`, `/alertas`) são network-first com cópia no cache.
 *   Dado velho servido como se fosse novo é pior que tela vazia, então a rede sempre tem a
 *   primeira palavra; o cache é o que sobra quando ela não responde, e a tela avisa.
 *
 * Nada de escrita passa por aqui. Fila de envio é do `app.js`, onde dá para mostrar o que
 * está pendente — um POST reenviado em silêncio pelo service worker é a origem clássica da
 * duplicata que ninguém explica depois.
 */

const VERSAO = "aegis-v2";
const SHELL = `${VERSAO}-shell`;
const DADOS = `${VERSAO}-dados`;

const ARQUIVOS_DO_SHELL = [
  "/",
  "/static/css/aegis.css",
  "/static/js/app.js",
  "/static/manifest.webmanifest",
  "/static/icons/aegis.svg",
  "/static/icons/aegis-maskable.svg",
  "/static/fonts/oswald-500.woff2",
  "/static/fonts/oswald-600.woff2",
  "/static/fonts/jetbrains-mono-400.woff2",
  "/static/fonts/jetbrains-mono-600.woff2",
];

// Só leitura entra no cache de dados. `/auth` fica de fora de propósito: token em cache é
// credencial deixada em disco no tablet compartilhado do convés.
const CACHEAVEL = [/^\/pts(\/|$|\?)/, /^\/indicadores/, /^\/alertas/];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(ARQUIVOS_DO_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((chaves) =>
        Promise.all(chaves.filter((c) => !c.startsWith(VERSAO)).map((c) => caches.delete(c)))
      )
      .then(() => self.clients.claim())
  );
});

function ehDoShell(url) {
  return url.pathname === "/" || url.pathname.startsWith("/static/");
}

function ehDadoCacheavel(url) {
  return CACHEAVEL.some((padrao) => padrao.test(url.pathname));
}

self.addEventListener("fetch", (evento) => {
  const requisicao = evento.request;
  if (requisicao.method !== "GET") return;

  const url = new URL(requisicao.url);
  if (url.origin !== self.location.origin) return;

  if (ehDoShell(url)) {
    // Cache primeiro (é o que faz abrir sem sinal), **e** revalidação em segundo plano.
    //
    // Só cache-first seria uma armadilha de implantação: com a versão fixa, uma correção no
    // `app.js` nunca chegaria a um tablet que já instalou o aplicativo — ele serviria o
    // arquivo velho para sempre, sem erro nenhum aparecendo. Depender de lembrar de trocar a
    // `VERSAO` a cada correção é depender de memória humana para uma falha silenciosa.
    evento.respondWith(
      caches.open(SHELL).then(async (cache) => {
        const emCache = await cache.match(requisicao);
        const daRede = fetch(requisicao)
          .then((resposta) => {
            if (resposta.ok) cache.put(requisicao, resposta.clone());
            return resposta;
          })
          .catch(() => null);
        // Sem cópia local, espera a rede. Com cópia, responde na hora e atualiza atrás:
        // o próximo carregamento já pega o novo.
        return emCache || (await daRede) || Response.error();
      })
    );
    return;
  }

  if (!ehDadoCacheavel(url)) return;

  evento.respondWith(
    fetch(requisicao)
      .then((resposta) => {
        // Só guarda o que veio bem. Guardar um 401 faria a tela mostrar "sem acesso" mesmo
        // depois de o login voltar.
        if (resposta.ok) {
          const copia = resposta.clone();
          caches.open(DADOS).then((cache) => cache.put(requisicao, copia));
        }
        return resposta;
      })
      .catch(async () => {
        const emCache = await caches.match(requisicao);
        if (emCache) {
          // O cabeçalho é o que permite a tela dizer "isto é de antes", em vez de deixar
          // alguém decidir a partir de um dado que pode ter horas.
          const cabecalhos = new Headers(emCache.headers);
          cabecalhos.set("X-Aegis-Do-Cache", "1");
          return new Response(await emCache.blob(), {
            status: emCache.status,
            headers: cabecalhos,
          });
        }
        return new Response(
          JSON.stringify({ detail: "Sem conexão e sem cópia local desta consulta." }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        );
      })
  );
});
