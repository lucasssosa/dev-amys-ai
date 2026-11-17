# Frontend e design

## Protótipo antes de tela

1. **Briefing:** objetivo da página, público, ação principal, conteúdo, referências.
2. **Wireframe:** estrutura e hierarquia, sem cor.
3. **Protótipo navegável** em HTML com os tokens do projeto.
4. **Decisão do usuário** sobre o protótipo.
5. Só então a implementação na stack do projeto.

Mudar um protótipo é barato; mudar uma tela implementada não.

## Design system

- Cores, tipografia, espaçamento, raios e sombras viram **tokens** (variáveis CSS), definidos
  num lugar só. Nada de valor solto no componente.
- Métricas do design system (valores soltos, cores fora dos tokens) não podem piorar.
- Componentes reutilizáveis antes de páginas.

## Construção

- Mobile first; teste em 375, 768 e 1440 px no mínimo.
- HTML semântico (`header`, `main`, `nav`, `section`, `button` de verdade).
- **Acessibilidade WCAG AA:** contraste, foco visível, navegação por teclado, `alt` em imagens,
  rótulos em formulários.
- Imagens otimizadas (WebP ou AVIF, tamanhos responsivos, `loading="lazy"` abaixo da dobra).
- Fontes: poucas famílias, `font-display: swap`.
- Formulários: validação no navegador para a experiência e no backend para a segurança.

## Landing pages

- Uma ação principal clara acima da dobra.
- SEO: `title` e `meta description` únicos, Open Graph para compartilhamento, dados
  estruturados quando fizer sentido, `sitemap.xml` e `robots.txt`.
- Performance como critério: Lighthouse acima de 90 em Performance, Acessibilidade, Boas
  práticas e SEO.
- Analytics e consentimento de cookies (LGPD) quando houver rastreamento.

## Verificação

- Capturas de tela nos tamanhos de tela do projeto, lidas por um leitor, não pelo coordenador.
- **Validação visual é do usuário.**
- Teste de tela com Playwright para os fluxos principais.
- Auditoria automática (Lighthouse e axe) no gate de promoção.
