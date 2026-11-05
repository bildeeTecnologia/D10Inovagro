# Deploy inicial de homologação (Coolify/VPS)

Este procedimento prepara um ambiente **de homologação**, não certifica prontidão para produção. Use somente dados sintéticos ou anonimizados. O repositório privado não torna privado um serviço publicado na internet.

## Limites e pré-requisitos

- Use projeto/banco Supabase **separado para staging**, sem CPFs, folha real ou credenciais de produção. A variável `DATABASE_URL` deve usar conexão PostgreSQL com TLS e credenciais restritas ao banco de staging.
- Mantenha este serviço atrás de VPN, allowlist de IP ou camada adicional de autenticação no proxy durante o piloto. HTTPS é obrigatório mesmo em homologação.
- O contêiner deliberadamente **não executa `migrate`, não cria superusuário e não roda `seed_demo`** ao iniciar. Faça backup e aplique migrations manualmente na etapa de release aprovada.
- A aplicação possui armazenamento local de mídia (`MEDIA_ROOT`) para uploads da pré-admissão. Este setup não configura object storage privado, antivírus, política de retenção ou backup desses arquivos. Portanto, não habilite uploads reais nem armazene documentos pessoais no piloto; mantenha a funcionalidade fora do escopo ou suspenda esses fluxos.
- Logs do Gunicorn podem conter informações operacionais. Restrinja acesso e retenção no Coolify; nunca registre segredos ou conteúdo de folha.

## Variáveis de ambiente no Coolify

Configure os valores no painel de variáveis/segredos do serviço (não em arquivo versionado, Dockerfile ou build args):

| Variável | Requisito para o piloto |
|---|---|
| `DJANGO_DEBUG` | `0` |
| `DJANGO_USE_WHITENOISE` | `1` no contêiner de homologação (já definido no Dockerfile). |
| `DJANGO_SECRET_KEY` | Segredo aleatório forte, exclusivo deste ambiente; não reutilizar local ou produção. |
| `DJANGO_COLLABORATOR_ID_KEY` | Segredo aleatório estável e exclusivo de staging. Não rotacionar sem plano, pois fingerprints existentes deixam de corresponder. |
| `DJANGO_ALLOWED_HOSTS` | Somente o hostname exato do domínio de homologação, sem esquema e sem wildcard. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origem HTTPS exata, por exemplo `https://homologacao.exemplo.com`. |
| `DATABASE_URL` | Connection string PostgreSQL **do staging**, credencial restrita, TLS. Não usar banco com folha real. |
| `SUPABASE_REALTIME_URL` | URL do projeto Supabase de staging. |
| `SUPABASE_PUBLISHABLE_KEY` | Publishable key do mesmo projeto; não é a service-role key. |
| `SUPABASE_REALTIME_SIGNING_KEY_ID` | `kid` da chave ES256 de assinatura que foi importada no projeto Supabase. |
| `SUPABASE_REALTIME_SIGNING_PRIVATE_KEY` | Chave privada ES256 em PEM, somente como Runtime Secret. Deixe vazia até a configuração; o app mantém o polling de contingência. |
| `SUPABASE_REALTIME_ISSUER` | Em geral `<SUPABASE_REALTIME_URL>/auth/v1`; pode ser omitida se esse for o issuer aceito pelo projeto. |
| `DJANGO_SECURE_SSL_REDIRECT` | `1` |
| `DJANGO_SESSION_COOKIE_SECURE` | `1` |
| `DJANGO_CSRF_COOKIE_SECURE` | `1` |
| `DJANGO_USE_X_FORWARDED_PROTO` | `1` somente se o proxy confiável do Coolify sobrescrever `X-Forwarded-Proto` com o esquema real; caso contrário, não habilitar antes de verificar como TLS é terminado. |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` no primeiro teste; depois de validar HTTPS, pode-se usar `300` ou `3600` para o piloto. Não habilitar preload nem includeSubDomains nesta fase. |

Gere as duas chaves fora do repositório, em máquina confiável, por exemplo com `python -c "import secrets; print(secrets.token_urlsafe(64))"`, e cole-as diretamente como secrets no Coolify. Nunca reutilize a `DJANGO_SECRET_KEY` atual do `.env` local.

## Configuração no Coolify

1. Crie um serviço Dockerfile apontando para o repositório/branch de homologação. Conceda ao Coolify acesso privado ao repositório pela integração de menor escopo disponível; proteja e revogue a credencial se houver suspeita de exposição.
2. Configure domínio, TLS automático e acesso de rede restrito. Encaminhe tráfego para a porta interna `8000`; não exponha essa porta diretamente à internet. Confirme que o proxy remove/substitui headers encaminhados enviados pelo cliente.
3. Defina as variáveis acima como runtime secrets e desative qualquer opção **Available during build/Build Variable** para `DATABASE_URL`, `DJANGO_SECRET_KEY` e `DJANGO_COLLABORATOR_ID_KEY`. O log de build deve deixar de listar esses nomes como `--build-arg`. O Dockerfile executa `collectstatic` isoladamente, com `DEBUG=False`, `DATABASE_URL` vazio e chaves fictícias exclusivas do build; inicia Gunicorn como usuário sem privilégios; o servidor de desenvolvimento do Django não é usado.
4. Build/deploy inicial. Confirme que o serviço está saudável via `https://<domínio>/login/`, que CSS/JS carregam e que o navegador não mostra conteúdo misto. Não habilite `DEBUG` para diagnosticar um serviço público.
5. Antes de cada release com migration: faça backup do banco staging e valide restauração; execute `python manage.py migrate --plan`, revise o plano e então aplique `python manage.py migrate` em comando de release aprovado. O comando de inicialização do contêiner não faz isso automaticamente. As migrations `0018_conference_broadcast` e `0019_conference_broadcast_hardening` configuram/reaplicam a policy privada e o trigger best-effort no PostgreSQL; em SQLite elas não alteram o banco.
6. Execute `python manage.py check --deploy` dentro do ambiente com as mesmas variáveis do serviço, antes de abrir o piloto. Revise todos os avisos e não os ignore sem justificativa documentada.
   Para homologação com `DJANGO_SECURE_HSTS_SECONDS=300`, os avisos `security.W005` (HSTS sem subdomínios) e `security.W021` (sem preload) são intencionais: não habilite subdomínios ou preload até provar que todos os domínios envolvidos usam HTTPS e decidir formalmente pelo preload. Avisos diferentes precisam ser investigados e corrigidos; não desative o check.
7. Crie contas individuais de teste, com senhas fortes e escopos mínimos. Não use `seed_demo` nem credenciais compartilhadas. Teste login/logout, CSRF, cookies, PWA install, cache offline, filas e sincronização usando unidade/competência sintéticas.
8. Verifique logs, firewall, backups e teste de restauração. Revogue acesso ao serviço quando o piloto terminar e elimine dados temporários conforme política acordada.

## Validação local do artefato

No ambiente de desenvolvimento, após instalar `requirements.txt` atualizado:

```powershell
python manage.py check
python manage.py collectstatic --noinput
```

O `check --deploy` local não representa o ambiente Coolify e pode produzir avisos diferentes. A validação relevante deve rodar com as variáveis e proxy reais de homologação. O computador de desenvolvimento atual não possui Docker CLI; portanto, o build do contêiner precisa ser confirmado pelo Coolify antes do uso.

## Critérios mínimos para iniciar o piloto

- [ ] Serviço usa HTTPS e hostname correto; HTTP redireciona para HTTPS.
- [ ] `DEBUG=False`, segredos exclusivos e fora de Git/logs/build args.
- [ ] Banco Supabase de staging separado e sem dados reais; rede/credencial limitadas.
- [ ] Serviço restrito a participantes autorizados; conta individual e escopo mínimo.
- [ ] `check --deploy` executado no contêiner com resultado revisado.
- [ ] `collectstatic` concluído; assets servidos e PWA atualiza versão do Service Worker.
- [ ] Migrations revisadas/aplicadas separadamente; backup e restauração comprovados.
- [ ] Fluxos de upload com dados pessoais não são usados até configurar armazenamento e proteção adequados.
- [ ] Testes de PWA/sincronização feitos apenas com dados sintéticos.
- [ ] Supabase Broadcast ativado só depois de instalar a chave pública ES256 e guardar a chave privada como Runtime Secret no Coolify.

Mesmo cumprindo este checklist, trata-se de homologação controlada; isso não autoriza uso com dados reais de folha nem equivale a auditoria de segurança ou prontidão de produção.
Configure os valores no painel de variáveis/segredos do serviço como **disponíveis em runtime**, não como Build Variables/build args. As credenciais do Supabase e as chaves Django não são necessárias para `collectstatic` e não devem ser passadas ao construtor.


## Páginas de erro para usuários

A aplicação usa respostas próprias para erros 400, 403, 404 e 500, e uma página genérica para rejeições CSRF. Elas não mostram exceções, traceback, caminhos internos ou o motivo técnico da falha. O contêiner assume `DJANGO_DEBUG=0` por padrão; mantenha esse valor também nas variáveis runtime do Coolify. Em homologação, valide que URL inexistente retorna a página 404 da marca e que POST sem token CSRF retorna uma mensagem genérica, sem ativar `DEBUG` para diagnóstico.

## Supabase Broadcast da Conferência

O código usa um trigger PostgreSQL para emitir somente `conference.changed` (sem nome, CPF, valor ou conteúdo do evento), em um tópico privado por tenant, unidade e competência. O endpoint Django exige a capability `review` e assina tokens ES256 de cinco minutos com apenas `tenant_id`, `unit_ids` e `competency_id`. A aplicação não usa a service-role key nem o segredo JWT legado do projeto. A SDK `supabase-js` é importada sob demanda de uma URL ESM versionada; se a rede/CDN ou o canal não estiver disponível, a tela mantém polling de contingência a cada 30 segundos. Se uma CSP for adotada, permita esse host ou planeje empacotar a SDK localmente.

1. Crie/importe uma chave de assinatura ES256 dedicada para o Supabase Realtime e obtenha o `kid` correspondente. Configure a chave pública no projeto Supabase e guarde a chave privada PEM exclusivamente no Coolify como `SUPABASE_REALTIME_SIGNING_PRIVATE_KEY`; não a coloque em Git, no `.env` compartilhado, em SQL, no navegador ou em imagem de contêiner. Configure também URL, publishable key e key ID no Coolify.
2. Revise as configurações de acesso a canais privados do projeto Supabase. A policy criada pela migration valida extensão, tenant, competência e unidade contra as claims do token. Não altere políticas globais de canais públicos sem verificar primeiro se outro fluxo do mesmo projeto Supabase depende delas.
3. Faça backup restaurável, revise `python manage.py migrate --plan` e aplique as migrations 0018/0019 por procedimento de release. A 0019 reaplica idempotentemente a definição final mesmo se a 0018 já tiver sido registrada em outro ambiente. O trigger em `core_fieldevent` cobre INSERT/UPDATE/DELETE. Falhas no envio do sinal geram warning e não revertem o lançamento; o conteúdo da mensagem é apenas um aviso de renovação.
4. Em homologação com contas sintéticas, confirme que o endpoint `/api/v1/realtime/conference-token/` responde somente a perfis com `review`, retorna cache-control `no-store`, e que claims/topics contêm apenas unidades autorizadas e a competência selecionada. Confirme que um usuário não recebe sinal de unidade fora de seu escopo.
5. Abra Conferência em um navegador e crie/alterne um evento sintético em outro. A lista deve atualizar sem recarregar a página inteira. Desligue o Realtime/CDN temporariamente: a interface deve continuar atualizando por polling de contingência a cada 30 segundos. Confirme também que um erro de broadcast não impede salvar o evento.

Se as variáveis de assinatura não estiverem presentes, o endpoint fica indisponível e a tela permanece operacional no modo de polling. A instalação da migration, a importação da chave no Supabase e a configuração de secrets são etapas distintas; o código local não altera a instância Supabase nem o serviço no Coolify.
