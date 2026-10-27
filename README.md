# Instagram Download Video

Aplicativo de desktop (Windows, macOS e Linux) para baixar vídeos do Instagram em lote, feito com Python + Tkinter e
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Funcionalidades

- **Vários links de uma vez**: cole, importe de um `.txt` ou digite (um por linha, ou separados por vírgula).
  Links repetidos e parâmetros de rastreio (`?igsh=...`) são removidos automaticamente.
- **Downloads simultâneos** (1 a 5) com **progresso por item**, velocidade e **progresso geral** do lote
  (finalizados, com sucesso, com erro, já baixados, cancelados).
- **Cancelar** o lote a qualquer momento.
- **Painel de estatísticas**: downloads concluídos, taxa de sucesso, total baixado e data do último salvamento.
- **Últimos salvamentos**: histórico com data, perfil, legenda, tamanho e arquivo. Dá para abrir o vídeo,
  mostrar na pasta, abrir o post no Instagram ou recolocar o link na lista.
- **Pular vídeos já baixados** (arquivo de registro do yt-dlp na pasta de destino).
- Suporte a **carrosséis** (vários vídeos num mesmo post).
- **Login via cookies** do navegador (Firefox, Chrome, Edge, Brave, Opera) ou de um arquivo `cookies.txt`.

## Onde ficam os arquivos

Nada do que é baixado vai para o repositório:

| O quê | Onde |
| --- | --- |
| Vídeos | Direto na pasta escolhida: `<pasta>/<perfil>_<data>_<id>.mp4` |
| Histórico | `<pasta>/historico_downloads.json` |
| Registro de já baixados | `<pasta>/.download_archive.txt` |
| Preferências do app | `%APPDATA%\InstagramVideoDownloader\config.json` (Windows) ou `~/.config/InstagramVideoDownloader/` |

Tudo o que o app grava fica numa mesma pasta, escolhida por você: no primeiro uso o app pergunta onde gravar, e dá para trocar a qualquer momento no botão **Escolher…** (a sugestão inicial é `Vídeos\Instagram Downloads`). Em `%APPDATA%` fica apenas a lembrança de qual pasta você escolheu. O app **recusa** pastas de destino dentro do repositório e o
`.gitignore` bloqueia vídeos, histórico e cookies como proteção extra. Cada pasta de destino tem o seu próprio
histórico: ao trocar de pasta, o painel mostra o histórico daquela pasta.

## Como usar

### Windows (mais simples)

Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o ambiente virtual e instala as dependências;
nas próximas, só atualiza o yt-dlp e abre o app.

### Manualmente

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python main.py
```

Requer Python 3.10 ou superior.

## Dicas

- **Login**: o Instagram costuma bloquear downloads sem login. Faça login no Instagram em um navegador e escolha
  esse navegador em *Cookies (login)*. No Windows, o **Firefox** é o mais confiável: o Chrome e o Edge
  criptografam os cookies e podem falhar ou exigir que o navegador esteja fechado. Outra opção é exportar um
  `cookies.txt` (formato Netscape) com uma extensão do navegador.
- **Qualidade máxima**: com o [ffmpeg](https://ffmpeg.org/download.html) instalado e no `PATH`, o app junta a
  melhor trilha de vídeo com a melhor de áudio. Sem ele, baixa o melhor arquivo único disponível.
- **Parou de funcionar?** O Instagram muda com frequência. Atualize o yt-dlp: `pip install -U yt-dlp`
  (o `iniciar.bat` já faz isso).
- Use com moderação: muitos downloads seguidos podem levar a bloqueios temporários na conta. Respeite os
  direitos autorais e os termos de uso do Instagram.

## Testes

```bash
python -m unittest discover -s tests -v
```

## Estrutura

```
main.py                     ponto de entrada
iniciar.bat                 instala dependências e abre o app (Windows)
insta_downloader/
  config.py                 preferências do usuário (fora do repositório)
  downloader.py             fila, downloads simultâneos e progresso (yt-dlp)
  history.py                histórico em JSON e estatísticas
  gui.py                    interface Tkinter
tests/                      testes unitários
```
