# Fechamento de Campo

Primeiro incremento do MVP: fundação Django para cadastros multiempresa, competências, colaboradores, eventos de campo e trilha de auditoria.

## Executar localmente

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Acesse `http://127.0.0.1:8000/` para abrir o painel da aplicação. A tela `/admin/` é o cadastro técnico do Django e exige uma conta de equipe.

## Homologação em VPS/Coolify

Para um deploy inicial controlado, consulte [DEPLOY_HOMOLOGACAO.md](DEPLOY_HOMOLOGACAO.md). O procedimento usa Dockerfile, Gunicorn e WhiteNoise, exige HTTPS e banco Supabase separado de staging, não executa migrations nem cria usuários automaticamente e proíbe dados reais de folha. Não use `runserver` em serviço exposto nem copie o `.env` local para a VPS.

Para encerrar a sessão ou trocar de usuário, use **Sair** no cabeçalho. O botão envia um POST protegido por CSRF, encerra a sessão no servidor e redireciona para `/login/`. Após a saída, acessar novamente uma página interna exige autenticação; abrir `/logout/` diretamente por GET não encerra a sessão.

Para validar a primeira prévia do líder de campo, acesse `http://127.0.0.1:8000/campo/`. A tela usa IndexedDB para manter lançamentos pendentes no aparelho e envia os eventos ao endpoint `/api/v1/events/sync/` quando há conexão.

Usuário de demonstração criado pelo comando `seed_demo`:

- usuário: `demo`
- senha: `demo12345`

Uso exclusivamente local, com dados sintéticos. Nunca execute `seed_demo` nem use essas credenciais em VPS, staging ou produção. O comando `seed_demo` configura esse usuário como administrador no ambiente local de demonstração. Para corrigir ou recriar o acesso local depois de uma alteração, execute novamente `python manage.py seed_demo`.

## Permissões por perfil e unidade

### Navegação por áreas

O menu administrativo apresenta no máximo seis acessos principais: **Visão geral**, **Pessoas**, **Operação**, **Fechamento**, **Relatórios** e **Configurações**, conforme o perfil. Pessoas reúne pré-admissões e carga cadastral; Operação reúne app do líder, lançamentos, calendário e comunicação; Fechamento reúne saúde da operação, regras/rubricas, conferência, importação da folha, pagamentos e encerramento da competência. As URLs operacionais existentes foram preservadas.

Cada área apresenta botões descritivos, orientação inicial e exemplos de uso expansíveis. As páginas internas indicam a área ativa e oferecem retorno para ela. No celular, os mesmos acessos administrativos ficam disponíveis em uma faixa compacta; o líder mantém sua navegação simplificada. A tela de login não apresenta menu administrativo. Os cartões respeitam as capacidades existentes e não concedem permissões novas.

Diretriz de UX: projetar também para pessoas sem experiência analítica. Priorizar linguagem simples, ações agrupadas por tarefa, explicação do resultado de cada ação e exemplos sob demanda, sem acumular funções no menu principal.

Cada acesso é armazenado em `UserScope`, relacionando usuário, cliente, perfil, empresa e unidade. Perfis operacionais (`dp`, `leader`, `management`, `finance` e `accountant`) precisam ter uma unidade preenchida. Para liberar mais de uma unidade, cadastre uma linha de escopo por unidade para o mesmo usuário. A empresa é validada automaticamente contra a unidade selecionada.

O perfil `platform` e o superusuário são exceções administrativas internas. Um escopo `platform` sem unidade pode operar todas as unidades do cliente; isso deve ser reservado à equipe da plataforma e permanecer auditado. Um usuário comum sem escopo de unidade não recebe dados operacionais.

Eventos pendentes podem ser corrigidos no Admin somente com justificativa e auditoria dos valores anterior e posterior. Eventos aprovados, eventos de competências fechadas, exclusões e criações diretas pelo Admin são bloqueados.

No ambiente local, abra `/admin/auth/user/`, edite o usuário e use a seção **Acessos por unidade** para adicionar ou remover as unidades permitidas. O backend aplica o mesmo filtro no dashboard, lançamentos, calendário, app do líder e sincronização offline; não basta alterar o menu do navegador para obter acesso.

O banco local padrão é SQLite para acelerar a validação de telas. Para homologação, preencha `DATABASE_URL` com a conexão PostgreSQL do projeto Supabase de desenvolvimento. Nunca coloque credenciais reais no repositório ou no JavaScript do navegador.

Em ambientes com `DATABASE_URL`, o padrão é `DEBUG=False`; forneça `DJANGO_SECRET_KEY` e `DJANGO_ALLOWED_HOSTS` próprios. O modo seguro ativa redirecionamento HTTPS, cookies seguros e HSTS. Configure `DJANGO_CSRF_TRUSTED_ORIGINS` quando o domínio publicado exigir origens explícitas. Não habilite `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` nem `DJANGO_SECURE_HSTS_PRELOAD` sem confirmar que todos os subdomínios são servidos exclusivamente por HTTPS. O fallback de chave e hosts locais existe somente para desenvolvimento sem `DATABASE_URL`.

O padrão provisório de papéis, rubricas, participantes e gates está documentado na [Matriz de Governança da Etapa 1](../outputs/Matriz_de_Governanca_Etapa_1.md). Os parâmetros provisórios servem somente para desenvolvimento com dados sintéticos e não representam validação trabalhista.

## Estado atual

O manual operacional está em [Manual do usuário — Fechamento de Campo](../outputs/Manual_do_Usuario_Fechamento_de_Campo.md). Ele explica acesso, perfis, unidades, app do líder, sincronização offline, regras e limitações da versão atual.

Implementado: tenant, empresa, unidade, escopo de usuário, competência, colaborador, vínculo, evento de campo com chave idempotente, auditoria, dashboard inicial, lançamento de evento, PWA inicial do líder, fila IndexedDB, endpoint de sincronização idempotente, isolamento por unidade, regras administrativas versionadas, conferência com aprovação/rejeição, fechamento com reabertura auditada, relatório de custo por unidade, configurações do usuário e testes automatizados de autorização.

Bloco 1 implementado: central de comunicação com pendências, mensagens, responsável, prazo, prioridade, status, notificações internas, filtros por unidade/competência/status/prioridade e timeline de auditoria. Acesso disponível em `/comunicacao/`.

Bloco 2 implementado: prévia de relatórios, filtros por tipo/empresa/unidade/competência/status, exportação auditada em XLSX e PDF e histórico de emissões. Acesso disponível em `/relatorios/`. As dependências `openpyxl` e `reportlab` estão declaradas em `requirements.txt`.

Relatório de custos calculados por evento: painel gráfico alinhado ao mockup `outputs/mockups/05_painel_custo_unidade.png`, com filtros por empresa, unidade, competência e status; cartões-resumo; barras de custo por unidade e tipo de evento; evolução de até 12 competências encerrando no período selecionado; matriz comparativa e detalhamento com exportação XLSX/PDF. A competência mais recente é selecionada por padrão e o status padrão é “Aprovado”. A fonte são os resultados de cálculo registrados; o valor não comprova pagamento aprovado, exportado ou efetuado. Eventos sem cálculo são sinalizados e ficam fora dos totais. Valores de folha mensal ou sem vínculo direto a evento não entram neste comparativo. Como não há volume produzido por unidade nem meta orçamentária registrados, o sistema não apresenta custo por produção, eficiência ou atingimento de meta.

Bloco 3 implementado: painel de saúde da operação, inconsistências persistentes, validação de eventos fora da competência, vínculos inválidos, eventos pendentes/rejeitados, ausência de regras publicadas, notificações de inconsistências críticas e registro de sincronização do PWA. Acesso disponível em `/saude/`.

Regra de remuneração implementada: salários combinado e CLT versionados por colaborador, empresa, unidade e vigência; dispensa por chuva aprovada substitui a diária do salário combinado pela diária CLT naquele dia; cálculo mensal com base de 30 dias, arredondamento somente no total e ciclo de pagamento mensal. Resultado disponível no relatório `Composição mensal CLT e combinado`. Migration: `0007_compensationversion_monthlycompensationresult_and_more.py`.

O diretório `Pjt_Models/` contém arquivos de referência enviados pelo cliente para mapear folha mensal, salário combinado, pagamento do dia 10, bonificações, descontos e relatórios líquidos. Os originais foram preservados e estão catalogados em `outputs/Inventario_de_Arquivos_de_Referencia.md`. Eles contêm dados restritos e não devem ser usados no ambiente demo ou enviados para repositórios públicos.

Módulo de pagamentos implementado: ciclos separados para folha mensal e dia 10, rubricas versionáveis, lançamentos financeiros auditáveis e tela `/pagamentos/`. A composição salarial mensal gera as rubricas `SAL_COMBINADO_NORMAL` e `SAL_CLT_CHUVA`; rubricas `ADICIONAL_12H`, `BONIFICACAO_DIA10`, `PENSAO` e `DESCONTO` estão preparadas para os próximos fluxos de lançamento/importação. Migration: `0008_paymentcycle_rubric_paymententry_and_more.py`.

Adicional 12h disponível no app do líder: botão destacado, quantidade fixa em uma ocorrência, funcionamento offline, cálculo pela regra publicada e geração no ciclo do dia 10 após aprovação do DP. Migration de choices: `0009_alter_calculationrule_event_type_and_more.py`.

Importador controlado disponível em `/importacao/`: aceita XLSX e PDF, calcula hash SHA-256 e mantém a prévia sem gravação financeira automática. O XLSX detecta aba/cabeçalho/metadados e mascara CPF. O PDF da folha mensal extrai os totais por colaborador, valida CNPJ/competência e concilia somente pelo código interno exato contra o ciclo mensal já gerado. A comparação é por proventos, descontos e líquido, inclusive diferenças individuais e totais; nenhum pagamento é criado, alterado ou aprovado.

A prévia PDF ainda exige conferência humana: rubricas e filial/unidade do RM não estão mapeadas; os totais internos são agregados por colaborador entre unidades; diferenças não têm tolerância configurada; não há decisão/aceite por linha e códigos desconhecidos não são conciliados por nome. O parser recusa documentos sem texto extraível, protegidos, acima de 200 páginas ou sem totais legíveis. `pdfplumber` está declarado em `requirements.txt`. Migration do lote: `0010_importbatch.py`.

A prévia também valida CNPJ, competência, colaborador por nome/código, unidade e vínculo empresa/unidade, informando linhas correspondidas e inconsistências por linha. Mesmo com validação aprovada, nenhum lançamento é efetivado.

A revisão individual por linha foi adicionada ao lote, com situação `Correspondida` ou `Erro` e observação operacional. Migration: `0011_importbatch_validation_rows.py`.

Pré-admissão MVP implementada em `/admissoes/`: criação de convite por DP/direção, link com token seguro, chave de acesso, expiração de 15 dias, formulário público sem anexos, salvamento parcial, envio para conferência, aprovação/devolução/cancelamento e campos configuráveis pelo Admin. Migration inicial: `0012_admissionfielddefinition_admissionrequest_and_more.py`.

Conversão controlada disponível após aprovação: **Conferir conversão → Converter em colaborador e vínculo**. DP/direção/plataforma precisam de acesso à unidade; superusuários e plataforma global são exceções administrativas. A tela exige nome, CPF válido, cargo, data de admissão, justificativa e confirmação explícita; matrícula no vínculo é opcional. A conversão identifica a pessoa pelo mesmo fingerprint de CPF da carga cadastral, reutiliza o cadastro somente com nome compatível e não altera dados existentes. Cadastros antigos sem identidade de CPF com o mesmo nome, pessoas inativas, matrículas de outra pessoa e vínculos sobrepostos na mesma unidade bloqueiam a operação para revisão. Não há associação automática por nome nem regularização automática de cadastros antigos.

A conversão é transacional, rastreia vínculo, responsável e data na pré-admissão e registra auditoria sem CPF bruto. Repetir a ação não duplica registros; o processo convertido não pode ser editado nem reaberto para o candidato pela interface. Nenhum salário, regra ou pagamento é criado. Os demais dados pessoais permanecem nas respostas da pré-admissão, sem cópia automática para o cadastro operacional. Migration: `0017_admission_conversion.py`. Homologação de concorrência em PostgreSQL permanece pendente.

PWA do líder reforçado: validação local e no servidor, fila IndexedDB com estados, tentativas e último erro, retry e remoção protegida, sincronização ao retornar conexão/aba, cache resiliente do Service Worker v2 e correção da quantidade variável nos eventos. A suíte atual possui 15 testes aprovados.

Correções da análise técnica: resultados e lançamentos de pagamento mensal agora são separados por colaborador/unidade; o formulário e o PWA respeitam a unidade e o vínculo ativo; ciclos de pagamento possuem aprovação auditada e bloqueiam fechamento incompleto; reabertura devolve ciclos/lançamentos ao estado de rascunho; ações de revisão da pré-admissão exigem POST e o candidato não altera dados após o envio; configuração de produção falha explicitamente sem segredo e hosts próprios.

Conferência detalhada: `/conferencia/` agora filtra por competência, unidade e status, apresenta totais por status, valores calculados e memória da regra, além das composições mensais por colaborador/unidade. Decisões de evento invalidam ciclos aprovados que precisam ser conferidos novamente.

Catálogo de rubricas na tela **Regras** (`/regras/`): DP/plataforma autorizados podem cadastrar código interno, descrição, tipo (provento, desconto ou informativa), situação, ciclo previsto, vigência e orientações, com justificativa e auditoria. O formulário inclui exemplos práticos. Novos cadastros começam com sugestão de inativos e sem pagamento/a definir. Informativas devem usar ciclo sem pagamento; cadastrar/ativar não publica cálculo, não cria eventos no app nem altera os pagamentos existentes. O código é preservado na edição e, para rubricas padrão ou já utilizadas em lançamentos, esta tela permite alterar somente orientações. O Django Admin continua sendo uma ferramenta técnica, não uma alternativa para contornar essas proteções. Migration: `0014_rubric_catalog_informative.py`. Os parâmetros das regras de cálculo continuam no Admin; as fórmulas atuais foram preservadas.

Aplicação de rubricas disponível em **Regras**: regras aprovadas por unidade permitem provento mensal fixo, provento fixo por ocorrência e associação informativa para conferência. Vínculos por colaborador admitem fim indeterminado, referência e valor esperado informativo. Exemplo: limpeza mensal de veículo usa regra fixa e vínculo; pensão de conferência usa rubrica informativa, sem gerar novo desconto. A modalidade por ocorrência pode ser disponibilizada no app do líder, inclusive na fila offline; o evento só gera valor depois da aprovação do DP. Uma ocorrência por regra/colaborador/data. Migration: `0015_rubric_applications.py`; Service Worker v3.

O fluxo é **cadastrar → aprovar regra → vincular/aprovar colaborador ou lançar/aprovar evento → gerar rubricas → conferir/aprovar ciclo**. A ação de geração aceita a competência explicitamente; dia 10 corresponde ao mês seguinte ao trabalho. A geração mantém origem identificada e memória, sem duplicação ao reprocessar. Regras/vínculos aprovados não têm edição livre; o encerramento com justificativa não pode cortar pagamentos já gerados nem atingir períodos fechados/aprovados. Mudanças de valor exigem nova vigência sem sobreposição. Rubricas referenciadas por regras ficam protegidas também no Admin.

Limites deliberados: valor mensal fixo exige vigência e emprego durante o mês inteiro; mês parcial bloqueia geração/fechamento sem presumir proporcionalidade. Não há novas fórmulas percentuais, sobre CLT/combinado, descontos automáticos, garantia líquida ou confronto automático de pensão com rubricas RM. Adiantamento é solicitação administrativa: não comprova pagamento nem gera compensação automática. Chuva e 12h mantêm os motores anteriores. Cálculo e geração exigem acesso às unidades dos vínculos/eventos envolvidos.

O relatório detalhado com percentual, prioridades e cronograma está em [Cronograma e Status do Projeto](../outputs/Cronograma_e_Status_do_Projeto.md).

O relatório consolidado mais recente, com tudo que foi implementado, testado, limitações e próximos passos, está em [Relatório Consolidado de Status — 27/10/2026](../outputs/Relatorio_Consolidado_Status_2026-10-27.md).

A visão estratégica de comunicação entre campo, administração e setor de pessoas, incluindo requisitos de relatórios XLSX/PDF, está em [Requisitos Estratégicos — Comunicação e Relatórios](../outputs/Requisitos_Estrategicos_Comunicacao_Relatorios.md).

Implementado parcialmente: motor de cálculo inicial para diária e hora extra, fechamento com validação de eventos, cálculos e ciclos aprovados, e memória de cálculo. Ainda pendente para o MVP: regras completas autorizadas, homologação do fluxo de fechamento, importação da folha final, mapa de rubricas, divergências, exportação contábil homologada, PostgreSQL/Supabase de homologação, backup/restauração e piloto em campo.
