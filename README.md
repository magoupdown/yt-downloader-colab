# ▶️ YT Downloader Pessoal (Google Colab)

[![Abrir no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/magoupdown/yt-downloader-colab/blob/main/YT_Downloader_Pessoal.ipynb)

**👆 Clique no botão acima para abrir o app direto no Google Colab.** Depois rode a célula 1️⃣ (login Google) e a célula 2️⃣ (abre o aplicativo).

Notebook do Google Colab com **interface de página web** para baixar vídeos e playlists do YouTube:

- 🎬 **Vídeo em MP4** em qualquer resolução disponível (144p até 8K, com fps e tamanho estimado)
- 🎵 **Somente áudio** em MP3, M4A/AAC, OPUS, FLAC, WAV ou original, com escolha de qualidade (96–320 kbps ou melhor VBR)
- 📃 **Vídeo único ou playlist completa** (com seleção item a item, filtro por título, "selecionar todos/nenhum/inverter")
- 👁 **Prévia** antes de baixar: miniatura clicável (player embutido), título, canal, duração, views, data e descrição
- 🧭 **Assistente em 5 etapas** (Link → Prévia → Formato → Confirmar → Download): cada escolha é perguntada e nada é baixado sem confirmação
- 🔐 **Login Google obrigatório** (célula 1) e **cookies da conta** para vídeos privados, +18 ou só para membros, com persistência automática no Drive
- 📊 Progresso em tempo real (velocidade, ETA, etapa de conversão), cancelamento, botão "Baixar" por arquivo, ZIP de tudo, cópia opcional para o Google Drive
- 📱 Responsivo, tema claro/escuro, mensagens de erro traduzidas e com orientação do que fazer

## Como usar

1. Abra `YT_Downloader_Pessoal.ipynb` no Google Colab (**Arquivo ▸ Fazer upload de notebook**, ou envie para o Drive e abra com o Colab).
2. Rode a célula **1️⃣** e faça login na conta Google (obrigatório). Deixe "conectar_google_drive" marcado para salvar cookies e downloads no Drive.
3. Rode a célula **2️⃣**. O aplicativo aparece abaixo dela. Cole o link e siga as etapas.

## Sobre os cookies

O Colab roda em um servidor do Google, então **não é tecnicamente possível ler os cookies do seu navegador automaticamente** (nem o login do Colab entrega cookies do YouTube). A solução implementada:

1. Exporte uma vez o `cookies.txt` com a extensão *Get cookies.txt LOCALLY* (Chrome/Edge) ou *cookies.txt* (Firefox), logado no youtube.com.
2. Carregue o arquivo dentro do app (seção *Cookies da sua conta*). O app aceita formato Netscape, JSON de extensões ou o cabeçalho `Cookie:`.
3. Ele é salvo em `Meu Drive/YT_Downloader/cookies.txt` e **carregado automaticamente** em todas as próximas sessões.

O botão **Testar** verifica se o YouTube reconhece a sessão. Cookies dão acesso à sua conta: não compartilhe o arquivo nem o notebook com cookies embutidos.

## Estrutura

```
youtube-downloader-colab/
├── YT_Downloader_Pessoal.ipynb   ← o notebook pronto para o Colab
├── README.md
└── src/
    ├── backend.py          ← funções Python (yt-dlp, cookies, downloads, servidor de arquivos)
    ├── app.html            ← interface (HTML/CSS/JS) chamando o Python pela ponte do Colab
    ├── build_notebook.py   ← gera o .ipynb a partir dos dois arquivos acima
    └── dev_server.py       ← servidor local para testar a interface fora do Colab
```

Para editar, altere `src/backend.py` ou `src/app.html` e rode:

```bash
python src/build_notebook.py .
```

## Observações

- O YouTube às vezes exige "confirme que você não é um robô" em IPs de servidores. Carregar os cookies resolve.
- Áudio do YouTube tem no máximo ~130–160 kbps (256 kbps em alguns casos). Escolher bitrate maior não melhora o som.
- Arquivos temporários ficam em `/content/yt_downloader/downloads` enquanto a sessão do Colab estiver ativa. A célula 3️⃣ limpa essa pasta.
- Uso pessoal. Respeite os termos do YouTube e os direitos dos criadores.
