# RelatÃ³rio de entrega acadÃªmica â€” NightPoint

**26/11/2026 â€” EM VALIDAÃ‡ÃƒO.** Este arquivo serÃ¡ consolidado com os resultados efetivos antes do commit de entrega. NÃ£o representa aprovaÃ§Ã£o antecipada.

## 1. Resumo executivo

ProtÃ³tipo de Aplicativo de Mobilidade Urbana â€” Processamento em Tempo Real para Arquitetura de Software/Uni-FACEF, professor Carlos Alberto Lucas. A entrega prioriza arquitetura materializada e execuÃ§Ã£o local, com funcionalidades parciais explicitadas.

## 2. Estado final do protÃ³tipo

Protótipo acadêmico independente com API/PostGIS próprios, seed reproduzível, testes direcionados e build Web concluídos. Execução visual e GPS constam abaixo, sem aprovação de produção.

## 3. Projeto principal

NightPoint-architecture, branch `architecture/to-be`. Melhorias de cartografia/GPS implementadas primeiro nesse projeto; documentaÃ§Ã£o interna e histÃ³rico preservados. Os caminhos locais de entrega sÃ£o informados na resposta ao responsÃ¡vel, sem criar dependÃªncia de caminho absoluto no pacote.

## 4. VersÃ£o acadÃªmica

NightPoint-Academic, repositÃ³rio independente na branch `codex/academic-delivery`. Arquivos selecionados de blobsGit, sem copiar histÃ³rico, ambientes locais, caches, credenciais ou configuraÃ§Ãµes Firebase. `ACADEMIC-PROVENANCE.json` registra origem e adaptaÃ§Ãµes.

## 5. Funcionalidades implementadas

AutenticaÃ§Ã£o sintÃ©tica, perfil/avatar, cinco abas e temas; eventos/descoberta/detalhes/ediÃ§Ã£o/cancelamento/lista prÃ³pria; Garagem privada1:N/principal/histÃ³rico/arquivo/restauraÃ§Ã£o; curtidas/participaÃ§Ãµes/comentÃ¡rios; REST/SSE; mapa com cartografia e geolocalizaÃ§Ã£o opcional/manual.

## 6. Funcionalidades parciais

AutenticaÃ§Ã£o acadÃªmica substitui somente o provedor real nesse ambiente explicitamente sintÃ©tico. PreferÃªncia de tema em memÃ³ria; SSE local aumprocesso. GPS depende de suporte/permissÃ£o do dispositivo/navegador e nÃ£o representa rastreamento persistido.

## 7. NÃ£o implementado nesta entrega

Rotas/geocodificaÃ§Ã£o avanÃ§ada, APK/Android validado, identidade/idade/MFA/recuperaÃ§Ã£o reais, integraÃ§Ãµes comerciais, gamificaÃ§Ã£o, personagens avanÃ§ados e produÃ§Ã£o. Itens opcionais nÃ£o foram usados para atrasar P0/P1.

## 8. Mapa

Tiles HTTPS do OpenStreetMap, atribuiÃ§Ã£o visÃ­vel e link de direitos, pan/zoom, centro de demonstraÃ§Ã£o emFranca, buscaAPI e marcadores autorizados com detalhe. Semdownloadoffline ou varredura emlote. Cartografia e fluxo visual: consultar o registro de demonstração em docs/EVIDENCIAS.md.

## 9. GPS/geolocalizaÃ§Ã£o

Porta `DeviceLocation`, adaptador `GeolocatorLocation` e `PositionModel`. Captura explÃ­cita, marcador local, centralizaÃ§Ã£o e stream local enquanto ativo; cancelamento ao sair/background. SemAPI/persistÃªncia no modelo da posiÃ§Ã£o, semtrajetÃ³rias. Busca manual disponÃ­vel emnegativa/indisponibilidade. A captura real depende da permissão e do dispositivo; o resultado observado está em docs/EVIDENCIAS.md. Negativa/indisponibilidade não é apresentada como fix GPS bem-sucedido.

## 10. Processamento em tempo real

PosiÃ§Ã£o local nÃ£o Ã© apresentada comoSSE. `scripts/demo_realtime.py` usa duas sessÃµes reais, espera frameSSE `changed` apÃ³s ediÃ§Ã£o confirmada e relÃªREST autorizado; restaura o tÃ­tulo ao final. APROVADO na cópia acadêmica: duas sessões, frame changed e REST com versão confirmada. Evidência JSON/log real preservada e resumida em docs/EVIDENCIAS.md. A consulta geoespacial Ã© verificada separadamente por `scripts/verify_demo.py`.

## 11. CoesÃ£o

MÃ³dulos Identity, Events, Discovery, Garage e Community agrupam regras porcapacidade. ApresentaÃ§Ã£o, aplicaÃ§Ã£o, domÃ­nio e adaptadores tÃªm responsabilidades distintas. `docs/ARCHITECTURE.md` relaciona responsabilidades e arquivos concretos aos critÃ©rios do enunciado.

## 12. Acoplamento

RepositoriesFlutter encapsulamHTTP; portas e contratos pÃºblicos isolam mÃ³dulos eSQL; composiÃ§Ã£o injeta implementaÃ§Ãµes. O banco/processo compartilhados mantÃªm acoplamento operacional assumido, sem rotular o sistema de microsserviÃ§os. VerificaÃ§Ã£o da cÃ³pia:51nÃ³sPython, grafo acÃ­clico e ownership vÃ¡lidos.

## 13. ConascÃªncia

Seis exemplos classificados na matriz: nome(camposJSON), tipo(versÃ£o), significado(visibilidade), posiÃ§Ã£o(latitude/longitude), execuÃ§Ã£o(commit antes de publicaÃ§Ã£o) e temporal(corrida porveÃ­culo principal). Cada linha identifica cÃ³digo, tratamento e impacto. SÃ£o exemplos reais analisados, nÃ£o alegaÃ§Ã£o de eliminaÃ§Ã£o de todoacoplamento.

## 14. Justificativas arquiteturais

MonÃ³lito modular reduz custo operacional do protÃ³tipo; camadas/portas preservam regras; PostgreSQL/PostGIS oferece integridade e distÃ¢ncia; REST dÃ¡ operaÃ§Ãµes explÃ­citas; SSE permite invalidaÃ§Ã£o seletiva seguida de reconsulta. Custos: coordenaÃ§Ã£o de contratos, dependÃªncia de rede e limite de processo. NÃ£o hÃ¡ capacidade/performance provada apenas por desenho.

## 15. Matriz do professor

`docs/ARCHITECTURE.md`: critÃ©rios de coesÃ£o(3,0p), acoplamento/conascÃªncia(3,0p) e evidÃªncias de arquitetura(3,0p), com mÃ³dulo/arquivo/demonstraÃ§Ã£o/limite. ReferÃªncia conceitual: Richards e Ford, *Fundamentos da Arquitetura de Software*, modularidade e trade-offs. Nenhuma nota Ã© atribuÃ­da pelo prÃ³prio trabalho.

## 16. Testes e resultados

Principal:5testes de mapa/posiÃ§Ã£o positivos, anÃ¡lise direcionada0. CÃ³pia acadÃªmica:Flutteranalyze completo0,17testes direcionados positivos em50s, AST/ownership51nÃ³s0. Verificação real da API aprovada: três encontros próximos, região distante vazia e acesso de outra persona ao veículo privado negado com404. InicializaÃ§Ã£o inicialDB falhou em180s e primeiro buildAPI excedeu600s; logs preservados, recuperaÃ§Ã£o do mesmo volume sem aumentar budgets. NÃ£o houve suÃ­te geral ou benchmark novo.

## 17. EvidÃªncias de execuÃ§Ã£o

Build realizado a partir deste repositório, API própria127.0.0.1:59655 e Web5174. RunID1aea48f9bd46401384627d5eee1425b5, migrations0008. Resumos/hashes e observações visuais em docs/EVIDENCIAS.md. Logs/recibos sensÃ­veis e dados gerados permanecem em `.artifacts`/`infra/local`, ignorados peloGit; a entrega versiona apenas resumos/hashes pÃºblicos pertinentes. NÃ£o inventar screenshots ou arquivos nÃ£o salvos.

## 18. Material para documento acadÃªmico

README(diagrama/execuÃ§Ã£o), `docs/ARCHITECTURE.md`(matriz e seis conascÃªncias), `docs/PROVEDORES.md`, contratos em `contracts`, mÃ³dulos reais e este relatÃ³rio. O documentoPDF/Word final Ã© elaborado/conferido separadamente, conforme instruÃ§Ã£o do responsÃ¡vel.

## 19. Limpeza realizada

ExportaÃ§Ã£o porallowlist/grafo de imports, Flutter com dependÃªncias necessÃ¡rias ao recorte, entry acadÃªmica explÃ­cita, origem/proveniÃªncia e nomes naturais de demonstraÃ§Ã£o. NÃ£o foi feita limpeza destrutiva no projeto principal.

## 20. ExcluÃ­do do pacote acadÃªmico

HistÃ³ricoGit original, prompts/AGENTS/instruÃ§Ãµes internas, auditorias/planejamento comercial, `.venv`, caches/builds/logs, dados/volumes/recibos privados, configuraÃ§Ãµes Firebase/credenciais e consumidores Flutter legados. Benchmarks avanÃ§ados foram removidos/desabilitados no pacote. Testes e contratos pertinentes permanecem.

## 21. Preservado no principal

DocumentaÃ§Ã£o interna, auditorias, planejamento, cÃ³digo legado, testes/evidÃªncias anteriores, branch/baseline protegidas e dados do ambiente principal. NÃ£o houve cÃ³pia de banco ou exclusÃ£o de dados.

## 22. SeguranÃ§a

InspeÃ§Ã£o inicial de176arquivos selecionados:nenhum arquivo proibido ou padrÃ£o pesquisado de chave/privatekey/caminho demÃ¡quina/resÃ­duo de assistÃªncia/SDK de negÃ³cio noFlutter. Busca delimitada nÃ£o Ã© garantia universal nemS01. O pacote selecionado foi revisado sem copiar configurações reais; arquivos gerados privados ficam ignorados. A inspeção final do bundle e fontes está em docs/EVIDENCIAS.md. Backend continua autorizando recursos; banco privado, APIloopback; nÃ£o aprovaSEC-001global ou produÃ§Ã£o.

## 23. Executar o protÃ³tipo

SeguirREADME:criarvenvPython3.13, `flutter pub get`, `python scripts/start_demo.py`, build/run comURL emitida e Web5174. SeedAPI-only reproduz perfis/3encontros/3veÃ­culosfictÃ­cios em alvo prÃ³prio. RecuperaÃ§Ã£o explÃ­cita conserva volume/prova. Nunca abrir templateindex porfileURL nem usar banco de outrocheckout.

## 24. Publicar noGitHub

Gitlocal independente, `.gitignore`, fontes/lockfiles/README/atribuiÃ§Ãµes prontos. Nenhumremote foi criado. Somente apÃ³s autorizaÃ§Ã£o, criar repositÃ³rio exclusivo, configurarremote e publicar a branch conformeREADME; binÃ¡rios futuros porRelease autorizada, fora do histÃ³ricoGit.

## 25. LimitaÃ§Ãµes e pendÃªncias

Permissões/GPS e Internet dependem do ambiente; geocodificação/rotas/APK não foram validados. Duas tentativas de construção excederam600s; imagem concluída foi recuperada e comparada com97arquivos/75versões, sem ampliar prazos ou trocar banco. Não houve auditoria geral nova. Desempenho e produÃ§Ã£o continuam sem aprovaÃ§Ã£o. A operaÃ§Ã£o funcional anterior teve positivos consolidados e rodada conjunta4pass/4fail/timeouts; esta entrega nÃ£o oculta esse histÃ³rico nem reexecuta auditorias/suÃ­tes extensas. Nenhuma polÃ­tica material de privacidade/idade/identidade real foi decidida implicitamente.

## 26. SHA de origem principal

`030ca722a7946237d916acf765589f1c518b2ad2`. AdaptaÃ§Ãµes especÃ­ficas da cÃ³pia, como centro da demonstraÃ§Ã£o e empacotamento/recuperaÃ§Ã£o, estÃ£o registradas noGit acadÃªmico/proveniÃªncia. Sem dependÃªncia de arquivos do checkout de origem.

## 27. Commit da versÃ£o acadÃªmica

Código de recuperação validado em6e5676a296d80d3596e4c34e6e1557a0b906059d; o fechamento documental e a proveniência atualizada constam em commits locais posteriores. O commit que contÃ©m o fechamento documental pode ser consultado noGit local; seu hash nÃ£o Ã© inserido emsi mesmo. A resposta final informa oHEAD observado.

## 28. Original preservado

O projeto NightPoint original foi consultado somente porleitura de componentes de mapa/GPS. NÃ£o houve alteraÃ§Ã£o de seus arquivos, branch, histÃ³rico, configuraÃ§Ã£o ou banco. Main e baseline protegidas serÃ£o conferidas no fechamento.

## 29. Nenhumpush

Nenhum push, repositÃ³rio remoto, Release ou implantaÃ§Ã£o emproduÃ§Ã£o executado. Comandos de publicaÃ§Ã£o noREADME sÃ£o instruÃ§Ãµes futuras condicionadas Ã  autorizaÃ§Ã£o.

## 30. Parecer de prontidÃ£o

Pronto para avaliação como protótipo arquitetural local, com funcionalidades parciais e limitações expressas. README, matriz/diagrama, seis conascências, contratos, testes e proveniência disponíveis. Nenhum remoto/push/Release/produção realizado.
