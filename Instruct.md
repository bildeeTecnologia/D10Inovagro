# Fechamento de Campo — escopo do projeto

Oct 23, 2026 · @Fabio

Plataforma de pré-folha e fechamento mensal para operações agrícolas com muitas unidades: app offline para os líderes de campo, motor de cálculo parametrizável, conferência automática com a folha final e painéis de custo por unidade. MVP estimado em 12 a 14 semanas (a validar), condicionado à adequação trabalhista do modelo de remuneração do cliente.

## Resumo e decisão pedida

Pedimos à direção aprovar um piloto em uma unidade do cliente e o MVP do Fechamento de Campo (nome de trabalho), depois de confirmada a adequação trabalhista do modelo de remuneração descrito abaixo.

- **O que é:** camada de pré-folha entre o campo e o escritório contábil. Os líderes lançam dispensas, horas extras, diárias, domingos e feriados no celular, mesmo sem sinal. O sistema calcula e o RH confere. Quando a folha final volta do escritório, ela é importada e conferida automaticamente, com as divergências apontadas por colaborador.
- **Para quem:** cliente que já usa outro produto nosso. Presta serviço agrícola em várias unidades, mantém 5 folhas de pagamento (5 CNPJs) e fecha o mês com planilhas, caderno e grupos de WhatsApp.
- **Não é:** um sistema de folha oficial. A folha, o eSocial e os recolhimentos continuam com o escritório contábil.
- **Prazo e porte:** MVP em 12 a 14 semanas com 1 desenvolvedor em tempo integral e, em tempo parcial, 1 designer de UX, 1 gestor de projeto e 1 responsável por testes (estimativa preliminar). Três fases, detalhadas no plano de entrega.

| Decisão pedida | Por que agora |
| --- | --- |
| Condicionar o início ao parecer de advogado trabalhista sobre o modelo de remuneração | Define quais regras o motor de cálculo pode conter (seção Escopo) |
| Aprovar o modelo comercial (implantação + mensalidade) | Sem ele não há proposta ao cliente |
| Alocar a equipe do MVP | Janela de 12 a 14 semanas |
| Aprovar piloto em 1 unidade | Reduz risco antes de levar às demais unidades |

## Contexto do cliente e dores

O fechamento do cliente depende de uma única analista de DP, de planilhas sem fórmulas e de um caderno, num período de pico que vai de setembro a fevereiro. Os dados abaixo vêm da reunião de levantamento de 23/10/2026 (1h39 de gravação).

| Área | Como é hoje | Consequência |
| --- | --- | --- |
| Entrada de dados | Líderes mandam dispensas, horas extras e diárias por WhatsApp; a analista imprime e digita | Retrabalho e risco de esquecimento ou erro de digitação |
| Cálculo | Planilha-base por empresa, calculadora e caderno; 55 pessoas só na planilha de pagamento complementar da maior empresa | Sem fórmulas, sem rastro, difícil explicar um valor a um gerente |
| Pagamento | Dois momentos: quinto dia útil (folha) e dia 10 (complemento que não passa pela folha) | Conformidade a tratar antes do desenvolvimento (próxima seção) |
| Conferência | Folha devolvida pela contabilidade é impressa e conferida linha a linha | Horas de conferência manual a cada ciclo |
| Cadastro | Admissões e rescisões ajustadas à mão nas planilhas; 27 admissões em um único dia e 10 rescisões no mês em um CNPJ | Planilhas desatualizadas |
| Relatórios | Proprietário pede todo mês o custo por unidade; histórico do ano está em cadernos | Uma semana ou mais para montar a consulta de um ano |
| Segurança | Um notebook; o backup online existente, segundo a própria analista, é difícil de restaurar em outra máquina | Perda total possível por roubo, defeito ou incêndio |
| Auditoria | Clientes finais exigem folha, eSocial, ponto e comprovantes para liberar o faturamento | Pacote montado manualmente |
| Conectividade | Unidades em fazendas sem sinal; o ponto digital dos colaboradores já funciona offline e sincroniza depois | O app dos líderes precisa seguir o mesmo princípio |

O ponto é registrado no celular de cada colaborador, com geolocalização e foto facial. Os líderes de unidade, por acordo com a gerência, não registram ponto.

## Escopo, fora de escopo e condição de conformidade

O sistema registra e calcula apenas remuneração declarada: tudo o que for pago a um colaborador entra como rubrica identificada no cálculo, na exportação à contabilidade e no demonstrativo.

| Dentro do escopo | Fora do escopo |
| --- | --- |
| Captura de eventos em campo pelos líderes (offline) | Qualquer pagamento ou rubrica que não seja informada à contabilidade |
| Cálculo parametrizável de eventos variáveis declarados: dispensas, horas extras, adicional noturno, diárias, domingos e feriados, adicionais, descontos legais e autorizados, adiantamentos | Cálculo de "líquido alvo" que ajuste valores para atingir um combinado sem encargos |
| Conferência, aprovação e trilha de auditoria | Edição de batidas de ponto para ocultar horas efetivamente trabalhadas |
| Exportação de eventos para a contabilidade, importação da folha final com conferência automática e lote de pagamento a partir de valores declarados | Renomear ou mascarar rubricas para esconder sua natureza |
| Cadastro, histórico, relatórios de custo por unidade e painéis | Folha oficial, eSocial e recolhimentos (permanecem com o escritório contábil) |
| Backup, segurança e pacote de evidências com documentos reais para auditorias dos clientes finais | Parecer jurídico (contratar advogado trabalhista) |

**Condições para iniciar o desenvolvimento**

1. Parecer de advogado trabalhista sobre a estrutura de remuneração do cliente (salário combinado, dispensas por chuva, adicionais e o segundo pagamento do dia 10). As regras do motor de cálculo saem desse parecer.
2. Plano de adequação do passivo existente. A RegularizaFGTS pode ser a porta de entrada, mas já há uma auditoria de FGTS em andamento para o mesmo grupo sob termo de confidencialidade; a direção deve avaliar separação de contratos e de responsáveis para evitar conflito de interesse.
3. Regra de ponto: o espelho reflete as batidas reais. Ajustes só com justificativa, autor e versão anterior preservada.

Sem essas três condições, a recomendação é não iniciar: um sistema que consolida pagamentos não declarados expõe o cliente e a nossa empresa como fornecedora.

## Visão da solução e fluxo mensal

O mês só segue para a contabilidade e para o pagamento depois de conferido, aprovado e fechado; a direção acompanha o custo por unidade a cada fechamento.

&#91;embedded content: fluxo mensal · 9 etapas, 1 retorno ao líder\]

Pendências encontradas na conferência voltam ao líder, e a folha final devolvida pela contabilidade é importada e conferida automaticamente com o cálculo; o analista resolve as divergências antes do pagamento. O pagamento pelo sistema entra na fase 2.

## Líder e analista: o que cada um precisa em cada momento

O sistema atende o líder no campo e a analista no meio de campo: o que importa é capturado no lançamento e verificado na conferência.

| Momento | Líder no campo | Analista (meio de campo) | O que o sistema garante |
| --- | --- | --- | --- |
| Lançamento | Registra em poucos toques, mesmo sem sinal: dispensa, hora extra, diária, domingo, feriado, adiantamento, ocorrência | Vê os lançamentos chegarem, com autor, motivo e anexo; corrige com justificativa | Bloqueia duplicidade e lançamento fora do período; guarda a versão anterior |
| Acompanhamento | Vê o que falta e o prazo | Vê o status por unidade e cobra pendências | Painel do ciclo e lembretes |
| Cálculo | Confirma o resumo da unidade (sem salários, se configurado) | Revê a memória de cálculo por colaborador | Regras versionadas aplicadas aos eventos |
| Conferência com a folha final | Recebe pedidos de esclarecimento sobre lançamentos apontados | Importa a folha final e vê as divergências por colaborador, com causa provável | Cruza cálculo e folha pelo mapa de rubricas e aplica a tolerância configurada |
| Envio e pagamento | Recebe a confirmação do fechamento | Exporta para a contabilidade e para o financeiro | Arquivos com data, autor e registro de integridade |
| Dúvida sobre um valor | Vê apenas os próprios lançamentos | Explica o valor com a memória de cálculo e o histórico | Histórico completo por colaborador |

## Perfis de usuário e permissões

Sete perfis, com acesso por empresa (CNPJ) e por unidade; todo acesso e toda alteração geram registro de auditoria.

| Perfil | Canal | Pode | Não pode |
| --- | --- | --- | --- |
| Analista de DP (administradora do cliente) | Portal web | Cadastros, parâmetros, conferência, fechamento, exportações, reabertura com justificativa | Apagar histórico ou trilha de auditoria |
| Líder de unidade | App no celular (PWA) | Lançar e corrigir eventos da sua unidade, aprovar pendências, ver o andamento do fechamento | Ver dados de outras unidades; ver salários (configurável) |
| Gerência e direção do cliente | Portal web (leitura) | Painéis de custo por unidade, comparativos, histórico, exportar relatórios | Alterar lançamentos |
| Financeiro | Portal web | Receber lote aprovado, registrar pagamento e anexar comprovante | Alterar valores aprovados |
| Contador externo | Portal web (leitura) | Baixar exportações, comentar divergências | Alterar lançamentos |
| Colaborador (fase 2) | App ou link seguro | Consultar o próprio demonstrativo e histórico | Ver dados de terceiros |
| Administrador da plataforma (nossa equipe) | Console interno | Configurar o cliente, dar suporte, gerir usuários | Acessar dados sem registro e motivo |

## Módulos e prioridade por fase

O MVP (fase 1) cobre o ciclo mensal completo de ponta a ponta para uma unidade piloto; as fases 2 e 3 ampliam pagamento, admissão e rescisão, férias, 13º e auditoria.

| Módulo | Função | Fase |
| --- | --- | --- |
| M1 Cadastros e estrutura | Empresas (CNPJ), unidades, centros de custo, funções, colaboradores, líderes | 1 |
| M2 Importação do cadastro | Importar relação de empregados do escritório contábil; marcar admitidos e desligados | 1 |
| M3 Lançamentos em campo | App offline para dispensas, horas extras, diárias, domingos, feriados e ocorrências | 1 |
| M4 Parametrização | Tabelas por função, unidade e período: valores, adicionais, regras | 1 |
| M5 Motor de cálculo e fechamento | Calcula eventos do período e bloqueia o mês após aprovação | 1 |
| M6 Conferência e aprovação | Pendências dos líderes, divergências com a contabilidade, aprovação em etapas | 1 |
| M7 Exportações | Arquivo de eventos para a contabilidade (fase 1); lote de pagamento (fase 2) | 1 e 2 |
| M8 Relatórios e painéis | Custo por unidade, por função e por período; histórico anual | 1 (básico), 3 (avançado) |
| M9 Descontos | Vales, empréstimos internos, consignado, pensão, aluguel, sinistro de frota, com autorização registrada | 1 |
| M10 Ponto | Importar espelho de ponto e conciliar com os lançamentos | 2 |
| M11 Admissão e rescisão | Checklists, documentos, previsão de verbas | 2 |
| M12 Demonstrativo | Extrato mensal ao colaborador | 2 |
| M13 Documentos e auditoria | Pacote de evidências por cliente final e período | 2 |
| M14 Férias e 13º | Previsão e conferência de verbas variáveis | 3 |
| M15 Segurança e continuidade | Perfis, trilha de auditoria, backup e recuperação (transversal) | 1 |
| M16 Conferência automática da folha final | Importa a folha final do escritório, mapeia rubricas, compara com o cálculo e aponta divergências por colaborador | 1 |
| M17 Adiantamentos | Pedido, aprovação, pagamento, desconto programado no fechamento e informe ao escritório | 1 |

## Mapa de telas

44 telas em cinco grupos: 11 no app dos líderes, 19 no portal do RH, 5 nos painéis da direção, 3 para financeiro e contabilidade e 6 de administração. O app dos líderes é a prioridade de usabilidade: poucos toques, textos curtos, funciona sem sinal.

### A. App do líder (celular, offline)

| ID | Tela | Para quê | Campos e ações-chave | Fase |
| --- | --- | --- | --- | --- |
| A1 | Entrada | Acesso rápido e seguro | PIN ou biometria; escolha da unidade quando houver mais de uma | 1 |
| A2 | Início da unidade | Ver o que falta | Equipe, pendências, prazo do fechamento, indicador de sincronização | 1 |
| A3 | Lançamento rápido | Registrar um evento em segundos | Tipo (dispensa, hora extra, diária, domingo, feriado, ocorrência), colaboradores (um ou vários), data ou período, observação, foto opcional | 1 |
| A4 | Jornada estendida | Registrar dias com jornada acima do padrão | Data, colaboradores, horas, motivo, quem autorizou | 1 |
| A5 | Domingos e feriados | Registrar trabalho em dia de descanso | Data, colaboradores, compensação ou pagamento | 1 |
| A6 | Calendário da unidade | Revisar o mês | Eventos por dia, edição até a data de corte, histórico de alterações | 1 |
| A7 | Fechamento do líder | Confirmar o mês | Resumo por colaborador, aceite do líder, lembrete de pendências | 1 |
| A8 | Fila de sincronização | Saber o que já foi enviado | Itens pendentes, erros, reenviar | 1 |
| A9 | Avisos | Receber prazos | Abertura do fechamento, cobranças, mensagens do RH | 2 |
| A10 | Equipe | Pedir inclusão ou desligamento | Lista, status, solicitação ao RH com justificativa | 2 |
| A11 | Adiantamento | Pedir adiantamento para um colaborador | Colaborador, valor, motivo, parcelas sugeridas, anexo; acompanha a aprovação | 1 |

### B. Portal do RH (web)

| ID | Tela | Para quê | Campos e ações-chave | Fase |
| --- | --- | --- | --- | --- |
| B1 | Entrada e empresa | Acesso com segundo fator | Login, MFA, seleção de empresa (CNPJ) | 1 |
| B2 | Painel do ciclo | Acompanhar o mês | Status por unidade, pendências, contagem até o quinto dia útil | 1 |
| B3 | Colaboradores | Localizar pessoas | Filtros por empresa, unidade, função, status; busca | 1 |
| B4 | Ficha do colaborador | Dados e histórico | Vínculo, função, unidade, remuneração contratual, descontos recorrentes, documentos, histórico de alterações | 1 |
| B5 | Importação do cadastro | Atualizar o cadastro | Envio do arquivo, prévia de novos, desligados e alterados, confirmação | 1 |
| B6 | Unidades e centros de custo | Estrutura da operação | Unidade, empresa, cliente final, líder responsável, região | 1 |
| B7 | Funções e valores | Tabelas por função | Piso, valores por unidade, vigência, histórico | 1 |
| B8 | Regras e adicionais | Parametrizar o cálculo | Insalubridade, periculosidade, horas extras, adicional noturno, diária, domingo e feriado; versões com vigência | 1 |
| B9 | Descontos e empréstimos | Controlar valores a descontar | Parcelas, saldo, autorização registrada, pensão com base configurável, sinistro de frota | 1 |
| B10 | Caixa de lançamentos | Revisar tudo que chegou | Filtros, edição com justificativa, anexos, quem lançou e quando | 1 |
| B11 | Conferência por colaborador | Explicar um valor | Memória de cálculo: eventos, rubricas, base, resultado | 1 |
| B12 | Divergências | Tratar cada divergência apontada | Responsável, comentário, correção do cálculo ou pedido de retificação à contabilidade, status | 1 |
| B13 | Fechamento do mês | Bloquear e liberar | Checklist, aprovação em etapas, reabertura com justificativa | 1 |
| B14 | Exportações | Gerar arquivos | Eventos para a contabilidade, relatórios em PDF e Excel | 1 |
| B15 | Cobrança aos líderes | Resolver pendências | Lista de líderes com pendências, envio de lembrete com um clique | 2 |
| B16 | Aprovação de adiantamentos | Decidir e registrar | Saldo a receber no mês, limite, autorização anexa, aprovar ou recusar, parcelas, comprovante de pagamento | 1 |
| B17 | Importação da folha final | Trazer a folha devolvida pela contabilidade | Envio do arquivo (planilha, texto ou PDF), leitura por colaborador (proventos, descontos, líquido), prévia e confirmação | 1 |
| B18 | Mapa de rubricas e tolerâncias | Ensinar o sistema a comparar | De-para entre rubricas da contabilidade e do sistema; tolerância em reais e em percentual; regras por empresa | 1 |
| B19 | Resultado da conferência | Ver o que bate e o que não bate | Lista por colaborador (confere, diverge, ausente de um lado), diferença, causa provável, filtro por unidade, envio da divergência ao líder ou à contabilidade | 1 |

### C. Painéis da direção (leitura)

| ID | Tela | Para quê | Campos e ações-chave | Fase |
| --- | --- | --- | --- | --- |
| C1 | Visão geral | Custo total do mês | Por empresa e por unidade; evolução de 12 meses | 1 |
| C2 | Custo por unidade | Substituir o relatório manual mensal | Colaboradores, custo por tipo de rubrica, comparativo mês a mês | 1 |
| C3 | Eventos e ausências | Entender a operação | Dispensas, horas extras e domingos por unidade e função | 3 |
| C4 | Histórico e comparativos | Consultar anos anteriores | Ano contra ano, filtros, exportação | 3 |
| C5 | Resumo mensal | Enviar sem retrabalho | PDF gerado e enviado por e-mail aos destinatários cadastrados | 3 |

### D. Financeiro e contabilidade

| ID | Tela | Para quê | Campos e ações-chave | Fase |
| --- | --- | --- | --- | --- |
| D1 | Lote de pagamento | Pagar a partir do aprovado | Lista conferida, total, arquivo para Pix em lote | 2 |
| D2 | Baixa e comprovantes | Fechar o ciclo | Status por pagamento, anexo do comprovante | 2 |
| D3 | Portal do contador | Trocar arquivos e dúvidas | Arquivos por competência, comentários por colaborador | 1 |

### E. Administração e segurança

| ID | Tela | Para quê | Campos e ações-chave | Fase |
| --- | --- | --- | --- | --- |
| E1 | Usuários e perfis | Controlar acessos | Convite, perfil, empresas e unidades permitidas, desativação | 1 |
| E2 | Trilha de auditoria | Saber quem fez o quê | Busca por usuário, colaborador, período e tipo de ação; exportação | 1 |
| E3 | Configurações | Calendário e prazos | Feriados, data de corte, notificações, base de 30 dias ou calendário | 1 |
| E4 | Backup e recuperação | Confiar na continuidade | Último backup, último teste de restauração, alertas | 1 |
| E5 | Console da plataforma | Operar vários clientes | Cadastro de clientes, planos, suporte com acesso registrado | 1 |
| E6 | Documentos e auditoria | Atender auditorias de clientes finais | Pacote por cliente final e período com documentos reais | 2 |

## Regras de negócio e motor de cálculo

O motor transforma eventos lançados em rubricas declaradas, usando regras parametrizáveis com vigência. Nenhuma fórmula fica no código: todas vivem em tabelas versionadas, e cada resultado guarda a memória de cálculo que o gerou. Os valores e fórmulas abaixo são pontos de partida a validar no parecer trabalhista.

| Evento ou rubrica | Regra parametrizável (ponto de partida) | Observação |
| --- | --- | --- |
| Dia trabalhado e diária | Valor mensal da função ÷ base de dias (padrão 30, configurável) | Base de dias definida em Configurações (E3) |
| Dispensa por chuva | Evento por dia e por colaborador, lançável em lote pelo líder; tratamento financeiro conforme parecer jurídico | Espelho de ponto registra o motivo |
| Hora extra | Percentual por faixa (50% e 100% como padrão) sobre o valor-hora da função | Fonte: espelho de ponto ou lançamento autorizado |
| Adicional noturno | Percentual e janela horária configuráveis | Aplicado sobre as horas na janela |
| Jornada estendida | Valor fixo por dia acima do padrão, definido por função e vigência | Exige motivo e autorização do líder |
| Domingo e feriado | Multiplicador configurável sobre a diária | Compensação como alternativa |
| Insalubridade e periculosidade | Percentual por função sobre a base legal definida no parecer | Tabela por função (B7) |
| Responsabilidade de frota | Valor fixo por período vinculado a um veículo | Cadastro do veículo e do responsável |
| Descontos recorrentes | Parcelas, saldo e autorização registrada | Vale interno, empréstimo, aluguel, sinistro de frota |
| Empréstimo consignado | Parcela informada pelo banco ou pela folha | Divergência vai para B12 |
| Pensão alimentícia | Percentual ou valor da sentença, sobre a base definida em decisão judicial | Base (salário mínimo, bruto ou líquido) configurável por colaborador |
| Admissão e desligamento no mês | Proporcional aos dias vigentes | Data vem da importação da folha |
| Adiantamento | Valor pedido até o saldo a receber no mês (limite configurável); desconto programado no fechamento, em parcela única ou parcelada | Exige aprovação e autorização registrada; tratamento (adiantamento ou empréstimo) conforme parecer jurídico; vai à contabilidade como rubrica própria |
| Conferência com a folha final | Compara, por colaborador, proventos, descontos e líquido calculados com os da folha importada, rubrica a rubrica pelo mapa de rubricas; diferença acima da tolerância vira divergência | Tolerância em reais e em percentual, por empresa; o sistema sugere a causa provável (evento sem rubrica, parcela diferente, vínculo alterado) |

**Validações do ciclo**

1. Nenhum lançamento fora do período aberto nem de colaborador sem vínculo ativo na data.
2. Lançamento duplicado (mesmo colaborador, evento e data) é bloqueado com aviso.
3. Evento sem motivo ou sem autor é rejeitado.
4. Alterações após o corte exigem justificativa e geram nova versão; a anterior fica preservada.
5. O mês só fecha com todas as unidades confirmadas ou com pendência justificada pelo RH.
6. Fechado o mês, o resultado é imutável; correções entram como ajuste na competência seguinte ou por reabertura com aprovação.
7. O espelho de ponto nunca é editado pelo sistema: divergências entre ponto e lançamento aparecem como alerta.
8. Adiantamento só é aprovado com saldo a receber suficiente e autorização anexada; o desconto entra no fechamento e vai à contabilidade como rubrica própria.
9. A conferência com a folha final só é encerrada com todas as divergências resolvidas ou justificadas; cada resolução guarda autor, data e motivo.

## Modelo de dados

Vinte e quatro entidades sustentam o produto; toda entidade tem identificador próprio, datas de criação e alteração e referência ao cliente (multi-cliente desde o início).

| Entidade | Campos principais | Observação |
| --- | --- | --- |
| Cliente (tenant) | Nome, plano, parâmetros gerais | Isola os dados de cada contratante |
| Empresa | CNPJ, razão social, escritório contábil | Um cliente tem várias empresas (5 no caso atual) |
| Unidade | Nome, empresa, cliente final, região, líder | Base do relatório de custo |
| Contrato de prestação | Cliente final, unidades atendidas, exigências de auditoria | Alimenta o pacote de evidências |
| Colaborador | Nome, CPF, contato, dados bancários e chave Pix | Dados pessoais protegidos (LGPD) |
| Vínculo | Empresa, unidade, função, admissão, desligamento, remuneração contratual, vigência | Histórico preservado a cada alteração |
| Função e tabela de valores | Nome, piso, valores por unidade, adicionais, vigência | Versionada |
| Regra de cálculo | Tipo de evento, fórmula parametrizada, vigência, aprovador | Versionada e auditável |
| Competência | Mês, empresa, status (aberta, em conferência, fechada), datas de corte | Controla o bloqueio |
| Evento | Colaborador, tipo, data ou período, quantidade, motivo, autor, origem, identificador de sincronização, versão | Registro bruto do campo, nunca apagado |
| Rubrica calculada | Evento de origem, regra aplicada, base, valor, versão da regra | Memória de cálculo |
| Resultado do colaborador | Competência, total de proventos, total de descontos, total a pagar | Imutável após o fechamento |
| Desconto recorrente | Tipo, valor, parcelas, saldo, autorização, anexo | Inclui pensão e consignado |
| Veículo | Identificação, responsável, período | Para responsabilidade e sinistros |
| Importação do cadastro | Arquivo, data, autor, diferenças encontradas | Antes de gravar, o RH confirma |
| Exportação | Tipo, competência, arquivo, hash, autor, data | Prova do que foi entregue |
| Lote de pagamento | Competência, itens, total, status | Fase 2 |
| Pagamento | Colaborador, valor, data, comprovante | Fase 2 |
| Usuário e perfil | Perfil, empresas e unidades permitidas, MFA | Acesso mínimo necessário |
| Registro de auditoria | Usuário, ação, entidade, antes, depois, data e origem | Somente inclusão, sem edição |
| Adiantamento | Colaborador, valor, motivo, parcelas, aprovador, autorização, pagamento, comprovante | Liga-se ao desconto programado no fechamento |
| Folha final importada | Competência, empresa, arquivo, data, autor, linhas por colaborador (proventos, descontos, líquido) | Origem da conferência automática |
| Mapa de rubricas | Rubrica da contabilidade, rubrica do sistema, regra de comparação, vigência | De-para por empresa |
| Conferência e divergência | Colaborador, competência, valor calculado, valor da folha, diferença, causa provável, status, responsável, resolução | Histórico preservado |

## Integrações

A fase 1 usa troca de arquivos, que não depende de APIs de terceiros e começa mais rápido; integrações diretas entram quando o cliente confirmar quais sistemas usa.

| Integração | Direção | Formato (a confirmar) | Fase |
| --- | --- | --- | --- |
| Folha do escritório contábil | Entrada: relação de empregados, admissões e desligamentos, e a folha final (proventos, descontos e líquido por colaborador) para conferência automática. Saída: eventos do período | Planilha ou layout do software da contabilidade; para a folha final, planilha, arquivo texto ou PDF com leitura estruturada (a confirmar) | 1 |
| Produto atual do cliente (outro produto nosso) | Cadastro e login compartilhados | A definir com a equipe do produto | 1 (definição) |
| E-mail | Saída: relatórios mensais e lembretes | SMTP ou serviço de envio | 1 |
| App de ponto | Entrada: espelho de ponto para conciliar | Arquivo de jornada (AFD ou AEJ) ou API, conforme o fornecedor | 2 |
| Banco e financeiro | Saída: lote de pagamento | Planilha para Pix em lote ou CNAB 240, conforme o banco | 2 |
| Lembretes aos líderes | Saída: notificações | Push do app; WhatsApp Business é opcional e tem custo por mensagem | 2 |

eSocial e recolhimentos ficam com a contabilidade: o sistema não transmite nada à Receita nem ao governo.

## Requisitos não funcionais e segurança

Os requisitos que mais pesam são funcionar sem sinal, proteger dados pessoais de centenas de trabalhadores e nunca depender de um único computador. Metas numéricas são propostas iniciais, a validar com a direção.

| Requisito | Abordagem e meta proposta |
| --- | --- |
| Offline-first | App instalável (PWA) com fila local; sincronização idempotente que não duplica lançamentos; conflitos geram alerta ao RH em vez de sobrescrever |
| Acesso | MFA para RH, financeiro e direção; PIN ou biometria no app; perfis por empresa e unidade; sessões com expiração |
| LGPD | Dados mínimos necessários; criptografia em trânsito e em repouso; CPF e dados bancários mascarados na tela; registro de acessos a dados sensíveis; contrato de operador com o cliente; relatório de impacto à proteção de dados |
| Auditoria | Registro somente de inclusão de toda criação, edição, fechamento e exportação, com autor, data, valor anterior e novo |
| Backup e recuperação | Backup automático diário com cópia em outra região; teste de restauração mensal; meta de perda máxima de dados de 1 hora e retorno em até 4 horas |
| Desempenho | Telas em até 2 segundos; cálculo do mês para 500 colaboradores em até 1 minuto; dimensionado para 1.000 colaboradores e 20 unidades por cliente |
| Disponibilidade | 99,5% no horário comercial, com janelas de manutenção fora do período de fechamento |
| Usabilidade no campo | Fonte grande, ícones, até 3 toques para lançar um evento, português simples; teste com 3 líderes antes do piloto |
| Retenção | Prazos de guarda de documentos trabalhistas conforme a legislação, a validar com o jurídico; anonimização após o prazo |
| Operação | Logs, alertas e página de status; acordo de nível de suporte a definir |
| Localização | Português do Brasil, fuso America/Sao\_Paulo, feriados nacionais e municipais por unidade |

## Arquitetura e stack

Sugerimos construir o núcleo próprio em tecnologias que a equipe já domina, em vez de adaptar uma folha completa de código aberto: a folha oficial fica com o escritório contábil, e o diferencial está na captura em campo e no fechamento por unidade.

| Camada | Escolha | Motivo |
| --- | --- | --- |
| Backend | Python com Django e Django REST Framework | Conhecimento da equipe; painel administrativo e controle de acesso prontos |
| Banco de dados | PostgreSQL | Transações, histórico, backup contínuo |
| Tarefas em segundo plano | Celery com Redis | Cálculo do mês, exportações, e-mails |
| App do líder | PWA (Vue ou React) com armazenamento local e service worker | Sem lojas de aplicativos, atualização imediata, funciona offline |
| Portal e painéis | Aplicação web responsiva | Mesmo acesso no computador do RH e no celular da direção |
| Arquivos | Armazenamento de objetos compatível com S3, criptografado | Anexos, exportações, comprovantes |
| Hospedagem | Nuvem, preferencialmente em região no Brasil, com contêineres | Latência e conformidade |
| Qualidade e operação | Testes automatizados nas regras de cálculo, integração contínua, ambientes de desenvolvimento, homologação e produção, monitoramento de erros | Regras financeiras exigem teste de regressão |

## Plano de entrega por fase

O MVP leva de 12 a 14 semanas depois dos pré-requisitos; as fases 2 e 3 somam mais 14 a 18 semanas. Todas as durações são estimativas preliminares, a refinar depois do protótipo de telas.

| Fase | Entregas | Duração |
| --- | --- | --- |
| 0. Pré-requisitos | Parecer jurídico; regras de cálculo validadas; layout de importação da contabilidade; protótipo de telas aprovado pelo cliente | 2 semanas, em paralelo à proposta |
| 1. MVP | Cadastros, importação da folha, parametrização, app offline dos líderes, caixa de lançamentos, motor de cálculo, conferência, fechamento, exportação para a contabilidade, importação da folha final com conferência automática, adiantamentos, painel de custo por unidade, backup e auditoria; piloto em 1 unidade | 12 a 14 semanas |
| 2. Operação completa | Lote de pagamento, demonstrativo ao colaborador, importação do ponto, admissão e rescisão, documentos e pacote de auditoria, avisos e cobrança aos líderes | 8 a 10 semanas |
| 3. Gestão | Painéis avançados, histórico e comparativos, resumo mensal por e-mail, férias e 13º | 6 a 8 semanas |

**Marcos do MVP, em semanas após o início**

| Semanas | Marco |
| --- | --- |
| 1 a 2 | Fundação técnica: multi-cliente, login, perfis, trilha de auditoria; protótipo navegável |
| 3 a 5 | Cadastros, importação da folha e parametrização |
| 5 a 8 | App do líder offline e caixa de lançamentos |
| 7 a 12 | Motor de cálculo, conferência, importação da folha final com conferência automática, adiantamentos, fechamento e exportações |
| 11 a 14 | Painel de custo, testes de carga e de restauração de backup, piloto em 1 unidade durante um ciclo mensal completo, rodando em paralelo ao processo atual |

**Equipe proposta:** 1 desenvolvedor em tempo integral e, em tempo parcial, 1 designer de UX, 1 gestor de projeto e 1 responsável por testes. Do lado do cliente: a analista de DP como dona do processo e 2 líderes no piloto.

**Modelo comercial (a decidir):** implantação por fase mais mensalidade por colaborador ativo, ou mensalidade fixa por empresa. Valores ficam para a proposta, depois do protótipo.

## Riscos e mitigações

O risco que decide o projeto é o jurídico; os demais são de adoção e de dados.

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Modelo de remuneração do cliente sem adequação trabalhista | Exposição do cliente e da nossa empresa como fornecedora; possível recusa em entregar | Condição de início no escopo: parecer jurídico e plano de adequação antes do desenvolvimento |
| Conflito de interesse com a auditoria de FGTS em andamento | Questionamento ético e contratual | Separar contratos e responsáveis; decisão da direção |
| Líderes não adotam o app | Volta ao WhatsApp e ao caderno | Interface mínima, teste com 3 líderes, piloto, treinamento curto, cobrança automática de pendências na fase 2 |
| Dados iniciais ruins (cadastro, valores, histórico) | Cálculos errados no piloto | Importação com prévia de diferenças; piloto em paralelo ao processo atual por um ciclo |
| Layout de importação da contabilidade desconhecido | Atraso na entrega da exportação | Levantar o software e o layout na fase 0; começar por planilha |
| Falta de sinal no campo | Perda de lançamentos | Fila local, sincronização idempotente, alerta de itens não enviados |
| Dependência de uma única analista no cliente | Gargalo e risco de continuidade | Perfis de substituto, documentação do processo, painel de status |
| Dados pessoais de muitos trabalhadores | Incidente e sanção da LGPD | Criptografia, MFA, acesso mínimo, registro de acessos, relatório de impacto |
| Escopo crescer para folha completa | Estouro de prazo e concorrência com a contabilidade | Escopo fechado por fase; folha oficial fica fora |
| Cliente já usa outro produto nosso | Integração mal definida | Definir na fase 0 o que é compartilhado: login, cadastro ou nenhum |
| Folha final em formato variável ou só em PDF | Conferência automática menos precisa e mais trabalho de leitura | Levantar o formato na fase 0; começar por planilha ou arquivo texto; ler PDF apenas se não houver alternativa, com revisão manual |

## Indicadores de sucesso do piloto

O piloto é bem-sucedido se o fechamento ficar mais rápido e rastreável sem aumentar divergências. As linhas de base ainda não existem: serão medidas no ciclo anterior ao piloto, e as metas abaixo são propostas.

| Indicador | Como medir | Meta proposta |
| --- | --- | --- |
| Tempo de fechamento da analista | Horas gastas por ciclo, medidas antes e durante o piloto | Redução de 50% |
| Lançamentos feitos pelo app | Eventos do app ÷ total de eventos da unidade | 90% ou mais |
| Divergências com a folha da contabilidade | Quantidade por 100 colaboradores | Queda a cada ciclo; no máximo 2 no segundo ciclo |
| Líderes sem confirmar no corte | Líderes pendentes ÷ líderes da unidade | 10% ou menos |
| Relatório de custo por unidade | Tempo para gerar | Menos de 5 minutos |
| Recuperação de dados | Teste mensal de restauração | 100% bem-sucedido |
| Satisfação de líderes e analista | Pesquisa de 3 perguntas ao final do ciclo | 4 de 5 ou mais |

## Perguntas em aberto e decisões

**Para a direção**

- [ ] Aceitar a condição de conformidade (parecer jurídico e plano de adequação antes de desenvolver)?
- [ ] Como tratar o conflito de interesse com a auditoria de FGTS em andamento para o mesmo grupo?
- [ ] Modelo comercial: implantação por fase mais mensalidade, ou mensalidade fixa?
- [ ] Quem compõe a equipe do MVP e a partir de quando?
- [ ] Produto para este cliente apenas, ou base multi-cliente para vender a outras operações agrícolas?

**Para o cliente**

- [ ] Qual software de folha o escritório contábil usa e qual layout de importação aceita?
- [ ] Qual é o app de ponto e o que ele exporta?
- [ ] Qual outro produto nosso o cliente já consome e o que deve ser compartilhado (login, cadastro)?
- [ ] Quem é o patrocinador no cliente e quem decide pelo proprietário?
- [ ] Qual unidade será o piloto e quem são os 2 líderes participantes?
- [ ] Os líderes podem ver valores de salário no app ou apenas eventos?
- [ ] Como o proprietário quer receber o custo por unidade: painel, PDF mensal ou ambos?
- [ ] Qual é a data de corte do fechamento e o prazo combinado com a contabilidade?
- [ ] Em quais formatos a folha final pode ser exportada (planilha, arquivo texto ou PDF) e quais rubricas ela usa?
- [ ] Como o escritório quer receber os adiantamentos e em qual competência lança o desconto?
- [ ] Qual diferença entre o cálculo e a folha deve ser tolerada na conferência automática, em reais e em percentual?

## Referências open source

Nenhum projeto aberto faz o fechamento por unidade com entrada pelos líderes em campo, mas quatro servem de referência de conceitos. Licenças GPL e AGPL exigem avaliação jurídica antes de qualquer reaproveitamento de código. Busca feita em 23/10/2026 nos resultados do GitHub e nas páginas dos projetos.

| Projeto | Licença | O que aproveitar |
| --- | --- | --- |
| [Frappe HRMS](https://github.com/frappe/hrms) | GPL v3 | Presença com geolocalização, turnos, estrutura de folha |
| [Odoo e OCA l10n-brazil (KMEE)](https://kmee.com.br/en/payroll-odoo-brazil/) | AGPL-3 | Regras trabalhistas brasileiras e tipos de afastamento |
| [OpenHRApp](https://github.com/mimnets/OpenHRApp) | MIT | PWA com presença por GPS e selfie, jornada de campo |
| [payroll-api](https://github.com/dennersousa/payroll-api) | A verificar | Conferência de cálculos de horas extras, adicional noturno e periculosidade |
| [OrangeHRM](https://github.com/orangehrm/orangehrm) | GPL | Descartado: integrações e API ficam em edição paga |

A reunião de levantamento (23/10/2026) é a fonte dos dados do cliente.
