# Evidências da entrega — 26/11/2026

- Cópia independente: API própria na porta 59655, Web na porta 5174, PostGIS privado, migrations 0008 e seed com nomes fictícios naturais.
- flutter analyze completo: nenhum problema. 17 testes direcionados aprovados em 50 s. Grafo/ownership: 51 módulos válidos.
- API real: três encontros próximos, região distante vazia; garagens A/B separadas, veículo de outro ator negado com HTTP 404.
- SSE real: duas sessões, alteração confirmada, frame changed e reconciliação REST aprovados.
- Build Web independente: código de saída 0, em 193,7 s; dry-run de Wasm positivo, sem CDN. Bundle inspecionado, NOTICES preservado e HTTP 200.
- Navegador: login como Organizador Demo, cartografia real de Franca com atribuição, três marcadores, detalhe pelo marcador e busca manual confirmados.
- GPS foi solicitado, mas não houve fix confirmado no navegador controlado. A espera por permissão pode permanecer pendente; a busca manual continuou funcionando. Permissão negada/cancelamento/resposta tardia também são cobertos por testes controlados, não por hardware real. Não foram registrados valores de localização real.
- Screenshots foram exibidos nas chamadas de automação do navegador da conversa; não há arquivo local de screenshot a entregar. JSON versionado contém resumos e hashes, sem tokens/recibos privados.
- Bootstrap inicial falhou em 180 s e duas construções excederam 600 s. Recuperado mesmo volume com atestação; processos órfãos próprios encerrados. Imagem concluída comparada com 97 arquivos e 75 versões. Não houve aumento dos limites.
- Falhas anteriores da operação funcional permanecem no principal; estes resultados não aprovam desempenho/produção/SEC global ou Android.

Detalhes e hashes: EVIDENCIAS.json. Logs brutos locais ficam em `.artifacts`, fora do Git; credenciais geradas/recibos privados em `infra/local` nunca devem ser publicados.
Inspeção final de fontes: 192 arquivos, nenhum arquivo sensível proibido ou padrão de credencial pesquisado. Duas correspondências textuais referem-se exclusivamente ao nome legítimo da branch codex/academic-delivery em instruções/proveniência; não são resíduos na interface e foram preservadas para não falsificar o Git.

## Conferência editorial final — 26/11/2026

Revisados os 185 arquivos rastreados: 180 arquivos de texto válidos em UTF-8 e cinco imagens PNG. Nenhum caminho sensível proibido rastreado ou credencial real identificado nos padrões pesquisados. Três candidatos foram conferidos: dois exemplos de URL em testes e uma referência à leitura de segredo gerado no Compose. Esta verificação é delimitada aos arquivos e padrões pesquisados. Os números das inspeções anteriores acima foram preservados e correspondem a seus respectivos recortes.

Corrigidos acentuação, palavras concatenadas e status provisório nos documentos; referências de Richards e Ford harmonizadas pelo título em português utilizado na disciplina, sem inventar dados do exemplar. Resultados, hashes das evidências, autoria e licenças preservados. Não foram alteradas funcionalidades nem executados benchmarks ou suítes extensas.

A pasta foi renomeada fisicamente para `C:\nightpointv2`, após uma tentativa inicial bloqueada pelo Windows. O caminho antigo `C:\NightPoint-Academic` permanece como junção de compatibilidade para os caminhos privados e montagens existentes, sem duplicação dos arquivos. Houve uma breve parada dos contêineres acadêmicos na tentativa inicial; eles foram reiniciados, sem recriar dados. A tentativa final de renomeação funcionou sem nova parada dos contêineres. O servidor Web foi reiniciado com o caminho novo. Web e prontidão da API responderam com HTTP 200; ambos os contêineres acadêmicos ficaram saudáveis. Nenhum serviço de outro projeto foi interrompido.
