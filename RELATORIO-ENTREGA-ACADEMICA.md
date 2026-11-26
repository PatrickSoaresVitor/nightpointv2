# Relatório de entrega acadêmica — NightPoint

**26/11/2026 — versão acadêmica aceita para preparação da entrega.** Revisão editorial final concluída; resultados e limitações preservados.

## 1. Resumo executivo

Protótipo de Aplicativo de Mobilidade Urbana — Processamento em Tempo Real para Arquitetura de Software/Uni-FACEF, professor Carlos Alberto Lucas. A entrega prioriza arquitetura materializada e execução local, com funcionalidades parciais explicitadas.

## 2. Estado final do protótipo

Protótipo acadêmico independente com API/PostGIS próprios, seed reproduzível, testes direcionados e build Web concluídos. Execução visual e GPS constam abaixo, sem aprovação de produção.

## 3. Projeto principal

NightPoint-architecture, branch `architecture/to-be`. As melhorias de cartografia e GPS foram implementadas primeiro nesse projeto; documentação interna e histórico foram preservados. A cópia acadêmica não depende de arquivos externos ao seu repositório.

## 4. Versão acadêmica

Repositório acadêmico independente na branch `codex/academic-delivery`, armazenado em `C:\nightpointv2` após renomeação física da pasta. O caminho anterior `C:\NightPoint-Academic` permanece como junção de compatibilidade, sem duplicação dos arquivos, para preservar os caminhos usados pela demonstração. Arquivos selecionados de blobs Git, sem copiar histórico, ambientes locais, caches, credenciais ou configurações Firebase. `ACADEMIC-PROVENANCE.json` registra origem e adaptações.

## 5. Funcionalidades implementadas

Autenticação sintética, perfil/avatar, cinco abas e temas; eventos, descoberta, detalhes, edição, cancelamento e lista própria; garagem privada com múltiplos veículos, principal opcional único, histórico, arquivo e restauração; curtidas, participações e comentários; REST/SSE; mapa com cartografia e geolocalização opcional, com alternativa manual.

## 6. Funcionalidades parciais

Autenticação acadêmica substitui somente o provedor real nesse ambiente explicitamente sintético. Preferência de tema em memória; SSE local a um processo. GPS depende de suporte/permissão do dispositivo/navegador e não representa rastreamento persistido.

## 7. Não implementado nesta entrega

Rotas e geocodificação avançada, APK/Android validado, identidade, idade, MFA e recuperação reais, integrações comerciais, gamificação, personagens avançados e produção. Os itens opcionais permaneceram fora das prioridades desta entrega.

## 8. Mapa

Tiles HTTPS do OpenStreetMap, atribuição visível e link de direitos, pan/zoom, centro de demonstração em Franca, busca pela API e marcadores autorizados com detalhe. Sem download offline ou varredura em lote. Cartografia e fluxo visual estão registrados em `docs/EVIDENCIAS.md`.

## 9. GPS/geolocalização

Porta `DeviceLocation`, adaptador `GeolocatorLocation` e `PositionModel`. Captura explícita, marcador local, centralização e stream local enquanto ativo; cancelamento ao sair ou passar para segundo plano. O modelo de posição não acessa a API nem persiste trajetórias. Busca manual disponível em caso de negativa ou indisponibilidade. A captura real depende da permissão e do dispositivo; não houve fix GPS confirmado no navegador da demonstração. O resultado observado está em `docs/EVIDENCIAS.md`.

## 10. Processamento em tempo real

Posição local não é apresentada como SSE. `scripts/demo_realtime.py` usa duas sessões reais, espera o frame SSE `changed` após edição confirmada e relê o estado REST autorizado; restaura o título ao final. Aprovado na cópia acadêmica: duas sessões, frame `changed` e REST com versão confirmada. Evidência JSON e log real preservados e resumidos em `docs/EVIDENCIAS.md`. A consulta geoespacial foi verificada separadamente por `scripts/verify_demo.py`.

## 11. Coesão

Módulos Identity, Events, Discovery, Garage e Community agrupam regras por capacidade. Apresentação, aplicação, domínio e adaptadores têm responsabilidades distintas. `docs/ARCHITECTURE.md` relaciona responsabilidades e arquivos concretos aos critérios do enunciado.

## 12. Acoplamento

Repositories Flutter encapsulam HTTP; portas e contratos públicos isolam módulos e SQL; a composição injeta implementações. O banco e o processo compartilhados mantêm acoplamento operacional assumido, sem rotular o sistema de microsserviços. Verificação da cópia: 51 nós Python, grafo acíclico e ownership válidos.

## 13. Conascência

Seis exemplos classificados na matriz: nome (campos JSON), tipo (versão), significado (visibilidade), posição (latitude/longitude), execução (commit antes de publicação) e temporal (corrida pelo veículo principal). Cada linha identifica código, tratamento e impacto. São exemplos reais analisados, sem alegar eliminação de todo acoplamento.

## 14. Justificativas arquiteturais

Monólito modular reduz custo operacional do protótipo; camadas/portas preservam regras; PostgreSQL/PostGIS oferece integridade e distância; REST dá operações explícitas; SSE permite invalidação seletiva seguida de reconsulta. Custos: coordenação de contratos, dependência de rede e limite de processo. Não há capacidade/performance provada apenas por desenho.

## 15. Matriz do professor

`docs/ARCHITECTURE.md`: critérios de coesão (3,0 pontos), acoplamento/conascência (3,0 pontos) e evidências de arquitetura (3,0 pontos), com módulo, arquivo, demonstração e limite. Referência conceitual: RICHARDS, Mark; FORD, Neal. *Fundamentos da Arquitetura de Software*, edição em português utilizada na disciplina, especialmente modularidade e decisões arquiteturais. Os dados de edição e paginação devem seguir o exemplar do trabalho acadêmico; não foram identificados neste pacote. Nenhuma nota é atribuída pelo próprio trabalho.

## 16. Testes e resultados

Projeto principal: cinco testes de mapa/posição aprovados e análise direcionada sem problemas. Cópia acadêmica: `flutter analyze` completo sem problemas; 17 testes direcionados aprovados em 50 s; análise AST/ownership de 51 nós aprovada. Verificação real da API aprovada: três encontros próximos, região distante vazia e acesso de outra persona ao veículo privado negado com HTTP 404. O bootstrap inicial do banco falhou em 180 s e a primeira construção da API excedeu 600 s; logs preservados, com recuperação do mesmo volume sem ampliar prazos. Não houve nova suíte geral ou benchmark.

## 17. Evidências de execução

Build realizado a partir deste repositório, com API própria em `http://127.0.0.1:59655` e Web em `http://127.0.0.1:5174/`, migrations até 0008. Identificador da execução, resumos, hashes e observações visuais estão em `docs/EVIDENCIAS.json` e `docs/EVIDENCIAS.md`. Logs, recibos sensíveis e dados gerados permanecem em `.artifacts` e `infra/local`, ignorados pelo Git; a entrega versiona apenas resumos e hashes públicos pertinentes. As capturas exibidas na conversa não foram salvas como arquivos locais.

## 18. Material para documento acadêmico

README (diagrama e execução), `docs/ARCHITECTURE.md` (matriz e seis conascências), `docs/PROVEDORES.md`, contratos em `contracts`, módulos reais e este relatório. O documento PDF/Word final é elaborado e conferido separadamente, conforme instrução do responsável.

## 19. Limpeza realizada

Exportação por lista explícita de arquivos e grafo de imports, Flutter com dependências necessárias ao recorte, ponto de entrada acadêmico explícito, origem/proveniência e nomes fictícios de demonstração. Não foi feita limpeza destrutiva no projeto principal.

## 20. Excluído do pacote acadêmico

Histórico Git original, prompts, AGENTS e instruções internas, auditorias e planejamento comercial, `.venv`, caches, builds, logs, dados, volumes e recibos privados, configurações Firebase, credenciais e consumidores Flutter legados. Benchmarks avançados foram removidos ou desabilitados no pacote. Testes e contratos pertinentes permanecem.

## 21. Preservado no principal

Documentação interna, auditorias, planejamento, código legado, testes/evidências anteriores, branch/baseline protegidas e dados do ambiente principal. Não houve cópia de banco ou exclusão de dados.

## 22. Segurança

Inspeção inicial de 176 arquivos selecionados: nenhum arquivo proibido ou padrão pesquisado de chave, chave privada, caminho de máquina, resíduo de assistência ou SDK de negócio no Flutter. A busca delimitada não equivale a auditoria universal ou aprovação de S01. O pacote foi revisado sem copiar configurações reais; arquivos gerados privados ficam ignorados. A inspeção final do bundle e fontes está em `docs/EVIDENCIAS.md`. O backend continua autorizando recursos; banco privado e API em loopback. SEC-001 global e produção não estão aprovados.

## 23. Executar o protótipo

Seguir o README: criar o ambiente virtual com Python 3.13, executar `flutter pub get` e `scripts/start_demo.py`, e gerar ou servir a Web com a URL de API emitida. O seed usa somente a API e reproduz perfis, três encontros e três veículos fictícios em alvo próprio. A recuperação explícita conserva volume e prova de identidade. Não abrir o template `web/index.html` por URL de arquivo nem usar banco de outro checkout.

## 24. Publicar no GitHub

Git local independente, `.gitignore`, fontes, lockfiles, README e atribuições preparados. Nenhum remote foi criado. Somente após autorização, criar repositório exclusivo e vazio, configurar o remote e publicar a branch conforme o README; binários futuros pertencem a uma Release autorizada, fora do histórico Git.

## 25. Limitações e pendências

Permissões/GPS e Internet dependem do ambiente; geocodificação, rotas e APK não foram validados. Duas tentativas de construção excederam 600 s; a imagem concluída foi recuperada e comparada com 97 arquivos e 75 versões, sem ampliar prazos ou trocar banco. Não houve nova auditoria geral. Desempenho e produção continuam sem aprovação. A operação funcional anterior teve resultados positivos consolidados e uma rodada conjunta com quatro aprovações e quatro falhas ou timeouts; esta entrega preserva esse histórico e não reexecuta auditorias ou suítes extensas. Nenhuma política material de privacidade, idade ou identidade real foi decidida implicitamente.

## 26. SHA de origem principal

`030ca722a7946237d916acf765589f1c518b2ad2`. Adaptações específicas da cópia, como centro da demonstração, empacotamento e recuperação, estão registradas no Git acadêmico e na proveniência. Não há dependência de arquivos do checkout de origem.

## 27. Commit da versão acadêmica

O código de recuperação validado e os fechamentos documentais estão registrados no histórico Git local. A proveniência dos arquivos de origem consta em `ACADEMIC-PROVENANCE.json`. Para consultar o commit atual, executar `git log -1 --oneline`.

## 28. Original preservado

Durante a preparação, o projeto NightPoint original foi consultado somente por leitura de componentes de mapa/GPS. Não houve alteração de seus arquivos, branch, histórico, configuração ou banco. A revisão editorial final e a renomeação da pasta foram restritas ao repositório acadêmico; os projetos de origem não foram reabertos ou modificados nesta etapa.

## 29. Nenhum push

Nenhum push, repositório remoto, Release ou implantação em produção executado. Os comandos de publicação no README são instruções futuras condicionadas à autorização.

## 30. Parecer de prontidão

Versão acadêmica aceita para preparação da entrega como protótipo arquitetural local, com funcionalidades parciais e limitações expressas. README, matriz/diagrama, seis conascências, contratos, testes e proveniência disponíveis. Revisão editorial final concluída, sem alteração de funcionalidades ou repetição de benchmarks e suítes extensas. Nenhum remote, push, Release ou implantação em produção realizado.
