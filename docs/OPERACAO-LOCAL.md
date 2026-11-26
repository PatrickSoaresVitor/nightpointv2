# Operação local da demonstração

Este documento reúne instruções técnicas complementares ao [README](../README.md). Os comandos são executados na raiz do repositório; no Windows, use PowerShell. Eles são instruções para operação futura, não novos testes ou builds executados nesta revisão documental.

## Configuração e isolamento

O launcher gera credenciais sintéticas, projeto Docker, volume e recibos próprios, aplica as migrations 0001–0008 e publica somente a API em loopback. O banco não tem porta publicada. A origem Web é `http://127.0.0.1:5174`. O estado público da execução fica em `.artifacts/academic/current-demo.json`. Credenciais geradas e recibos privados ficam em `infra/local`; ambos os diretórios estão ignorados pelo Git.

`config.example.json` descreve valores de exemplo; não é carregado automaticamente. A configuração efetiva vem dos scripts e do estado emitido pelo launcher. Não preencher credenciais pessoais ou configurar Firebase real.

## Seed interrompido

Se houver falha durante o seed, conferir o alvo próprio e executar explicitamente:

```powershell
$demo = Get-Content .artifacts/academic/current-demo.json -Raw | ConvertFrom-Json
.venv\Scripts\python.exe infra/seed_demo.py --run-id $demo.run_id
```

## Bootstrap ou construção interrompidos

Se o primeiro bootstrap ou a construção da API forem interrompidos, o volume e o RunID ficam preservados. Conferir `preparation.json` do alvo próprio e recuperar explicitamente com `.venv\Scripts\python.exe scripts/resume_demo.py --run-id RUN_ID`. A recuperação valida dono/volume/arquivos privados, exige a função de bootstrap concluída e repete a prova de identidade do cluster, mantendo 180 s de startup e 600 s por comando. Aceita etapa já atestada somente com proveniência da interrupção e sem demo concluída. Não cria marcador artificial nem descarta volume. Não usar outro RunID ou banco por inferência. A imagem evita gerar bytecode durante instalação, mantendo versões fixas e `pip check`.

Se o estado indicar uma demonstração concluída que está indisponível, conferir seus contêineres e recibos antes de operar. A recuperação de preparação incompleta não deve ser usada para contornar a identidade de um alvo concluído. Não editar provas ou credenciais para forçar a recuperação.

## Verificações opcionais da demonstração

```powershell
$demo = Get-Content .artifacts/academic/current-demo.json -Raw | ConvertFrom-Json
.venv\Scripts\python.exe scripts/demo_realtime.py --run-id $demo.run_id
.venv\Scripts\python.exe scripts/verify_demo.py --run-id $demo.run_id
```

O primeiro script usa duas sessões reais, confirma SSE e reconciliação REST, e restaura o título do encontro ao final. O segundo consulta pontos fictícios próximos e distantes e verifica a negação de acesso ao veículo de outra persona. Ambos usam somente a API da própria demonstração atestada.

## Encerramento e outro alvo

```powershell
$demo = Get-Content .artifacts/academic/current-demo.json -Raw | ConvertFrom-Json
.venv\Scripts\python.exe infra/stop_demo.py $demo.run_id
```

O encerramento para somente os contêineres próprios e preserva volume e prova de identidade. Para outra base, criar explicitamente um novo alvo com `infra/test_environment.py --demo`, mantendo `NP_DEMO_WEB_ORIGIN=http://127.0.0.1:5174` no ambiente da sessão. Não apagar o alvo anterior, usar `prune`/`down -v` ou encerrar projetos alheios. Os artefatos de uma execução local podem conter caminhos absolutos; mover a pasta requer preservar a validade desses caminhos e das montagens existentes, sem falsificar recibos.
