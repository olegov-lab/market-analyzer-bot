# Agents Registry — BTC Monitor

## Model Distribution

| Model | Count | Agents |
|-------|-------|--------|
| **DeepSeek V4 Pro** | 10 | Break-Hunter, accountant, lawyer, project_manager, business_consultant, business_strategist, finance_analyst, Market-Brain, data_analyst, Rapid-Dev |
| **GLM-5.1** | 12 | hr_recruiter, seller, advertiser, pr_specialist, seo_specialist, smm_specialist, writer, content_producer, editor, Prompt-Master, teacher, Sigma-Architect |
| **Kimi K2.6** | 3 | screenwriter, ux_designer, ui_designer |

---

## All Agents (25)

### 1. Sigma-Architect — `architect`
- **Model:** GLM-5.1
- **Role:** Главный архитектор
- **Style:** structured, logical, system-level reasoning, long-context planning
- **Tasks:** проектирует модули, API, БД, пайплайны, масштабирование, производительность

### 2. Rapid-Dev — `developer`
- **Model:** DeepSeek V4 Pro
- **Role:** Главный разработчик
- **Style:** clean code, pythonic, fast implementation, practical
- **Tasks:** пишет Python-код, SOLID/DRY/KISS, рефакторит, дебажит

### 3. Market-Brain — `marketbrain`
- **Model:** DeepSeek V4 Pro
- **Role:** Аналитик финансовых рынков
- **Style:** structured financial analysis, risk assessment, clarity
- **Tasks:** анализ новостей, драйверов, рисков, инвест-рекомендации

### 4. Break-Hunter — `tester`
- **Model:** DeepSeek V4 Pro
- **Role:** Главный тестировщик
- **Style:** aggressive testing, edge-case hunting, validation
- **Tasks:** поиск багов, уязвимостей, крэш-тесты, тест-кейсы

### 5. Prompt-Master — `promptmaster`
- **Model:** GLM-5.1
- **Role:** Эксперт по промптам
- **Style:** clear, concise, optimized prompts, linguistic precision
- **Tasks:** создаёт и оптимизирует промпты, структурирует блоками

### 6. teacher
- **Model:** GLM-5.1
- **Temperature:** 0.4
- **Tasks:** объясняет темы, создаёт уроки, учебные планы, упражнения

### 7. data_analyst
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.35
- **Tasks:** анализирует таблицы, метрики, строит гипотезы

### 8. finance_analyst
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.35
- **Tasks:** анализирует компании, отчётность, мультипликаторы, строит портфели

### 9. business_strategist
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.5
- **Tasks:** долгосрочные стратегии, рынки, тренды, позиционирование

### 10. business_consultant
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.45
- **Tasks:** анализ рынка, конкурентов, процессов, рекомендации

### 11. project_manager
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.45
- **Tasks:** планирование, декомпозиция, сроки, риски, коммуникация

### 12. lawyer
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.2
- **Tasks:** юридические ответы, анализ документов, законы

### 13. accountant
- **Model:** DeepSeek V4 Pro
- **Temperature:** 0.25
- **Tasks:** проводки, отчётность, налоги, амортизация, баланс

### 14. editor
- **Model:** GLM-5.1
- **Temperature:** 0.3
- **Tasks:** улучшение текста, стиль, орфография, структура

### 15. writer
- **Model:** GLM-5.1
- **Temperature:** 0.85
- **Tasks:** художественные тексты, описания, истории, образы

### 16. content_producer
- **Model:** GLM-5.1
- **Temperature:** 0.8
- **Tasks:** форматы, сценарии, рубрики, контент-сетки

### 17. smm_specialist
- **Model:** GLM-5.1
- **Temperature:** 0.75
- **Tasks:** посты, сторис, Reels/TikTok, контент-планы, вовлечение

### 18. seo_specialist
- **Model:** GLM-5.1
- **Temperature:** 0.55
- **Tasks:** семантика, оптимизация, анализ конкурентов, SEO-тексты

### 19. pr_specialist
- **Model:** GLM-5.1
- **Temperature:** 0.7
- **Tasks:** имидж, публичные сообщения, репутация, пресс-релизы

### 20. advertiser
- **Model:** GLM-5.1
- **Temperature:** 0.85
- **Tasks:** креативы, офферы, слоганы, рекламные тексты

### 21. seller
- **Model:** GLM-5.1
- **Temperature:** 0.75
- **Tasks:** продающие тексты, работа с возражениями, усиление ценности

### 22. hr_recruiter
- **Model:** GLM-5.1
- **Temperature:** 0.45
- **Tasks:** вакансии, интервью, оценка компетенций

### 23. ui_designer
- **Model:** Kimi K2.6
- **Temperature:** 0.65
- **Tasks:** цвета, типографика, сетки, визуальный стиль

### 24. ux_designer
- **Model:** Kimi K2.6
- **Temperature:** 0.6
- **Tasks:** сценарии, CJM, улучшения UX, wireframes

### 25. screenwriter
- **Model:** Kimi K2.6
- **Temperature:** 0.9
- **Tasks:** сцены, диалоги, структура, драматургия

---

## By Temperature

| Temp | Agents |
|------|--------|
| 0.20 | lawyer |
| 0.25 | accountant |
| 0.30 | editor |
| 0.35 | data_analyst, finance_analyst |
| 0.40 | teacher |
| 0.45 | hr_recruiter, business_consultant, project_manager |
| 0.50 | business_strategist |
| 0.55 | seo_specialist |
| 0.60 | ux_designer |
| 0.65 | ui_designer |
| 0.70 | pr_specialist |
| 0.75 | seller, smm_specialist |
| 0.80 | content_producer |
| 0.85 | writer, advertiser |
| 0.90 | screenwriter |
| — (system) | Sigma-Architect, Rapid-Dev, Market-Brain, Break-Hunter, Prompt-Master |

## By Role

| Role | Agents |
|------|--------|
| **Core Dev** | Sigma-Architect, Rapid-Dev, Break-Hunter |
| **Crypto/Finance** | Market-Brain, finance_analyst, data_analyst, accountant |
| **Content** | editor, writer, content_producer, screenwriter, teacher, Prompt-Master |
| **Marketing** | smm_specialist, seo_specialist, pr_specialist, advertiser, seller |
| **Design** | ui_designer, ux_designer |
| **Business** | business_strategist, business_consultant, project_manager, lawyer, hr_recruiter |
