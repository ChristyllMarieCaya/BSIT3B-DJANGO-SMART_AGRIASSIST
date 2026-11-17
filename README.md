# SMART AGRIASSIST

**Project team**

- CAYA, CHRISTYLL MARIE L.
- BULAHAN, MAILEN
- ADRIAS, IRISH ANN

# DEVELOPMENT OF SMART AGRIASSIST: AN INTELLIGENT PHILIPPINE FARM MANAGEMENT AND AI-POWERED DECISION-SUPPORT SYSTEM
**BSIT Capstone Project Concept Paper**

## INTRODUCTION

### Background of the Project
Agriculture remains a cornerstone of the Philippine economy, employing roughly one-fourth of the national labor force and sustaining rural livelihoods in farming communities such as Kabankalan City and Negros Occidental (Philippine Statistics Authority [PSA], 2024). However, many Filipino smallholder farmers still rely on manual observation and paper records, resulting in disorganized crop scheduling, unmonitored plant disease outbreaks, and delayed responses to erratic tropical weather events (World Bank, 2019; Department of Agriculture [DA], 2024).

To address these gaps, the proposed project will develop Smart AgriAssist, a centralized web-based intelligent farm management and AI-powered decision-support platform tailored to the Philippine agricultural setting. Built on a 14-entity relational database architecture, the system will integrate registered crop lifecycle tracking, seasonal crop guidelines, field visual identification logs, computer-vision-assisted crop disease diagnosis, an interactive AI agronomy assistant, live weather monitoring with automated threshold alerts, a searchable crop catalog, and role-based user administration for Farmers and System Administrators.

### Statement of the Problem or Project Objectives
The main objective of this project is to design, develop, and evaluate Smart AgriAssist, an intelligent web-based farm management and AI decision-support platform tailored to the Philippine setting, to streamline farm record-keeping, crop lifecycle monitoring, AI-assisted disease diagnosis, and weather-informed agricultural planning.

Specifically, the project aims to accomplish the following technical objectives:
1. Develop a secure user authentication and role-based access control module (Farmers and System Administrators) with activity logging and persistent user preferences for farm GPS coordinates, measurement units, language, and AI response styles.
2. Establish an Administrative Management Console that will allow System Administrators to manage user accounts and permissions, curate the Philippine Crop Catalog and reference growth stage repositories, and monitor system-wide agricultural logs.
3. Implement a Crop Growth Monitoring, Seasonal Guideline, and Field Scouting module that will allow farmers to register active crops (recording variety, planting date, field name, planted area, and expected harvest duration), manage seasonal crop plans, and log visual field identification observations.
4. Integrate an AI-powered Agri Assistant (supporting multi-turn conversation threads and image attachments) that will conduct agronomic consultations and analyze uploaded crop photos to identify possible diseases, pests, or nutrient deficiencies with confidence scores, contributing weather factors, treatment steps, and technician escalation advice.
5. Build a searchable Crop Catalog reference module that will provide detailed botanical profiles, soil and climate requirements, watering and fertilizer schedules, pest and disease management, and harvesting guidelines across regional crop categories.
6. Integrate an Agro-Meteorology and Weather Alert module connected to live weather APIs (Open-Meteo) that will track daily farm weather records (temperature, rainfall, humidity, and wind speed) and trigger automated severe weather alerts based on customizable rainfall, wind, and temperature thresholds.
7. Build an Automated Farm Task Scheduler and Multi-Channel Notification Center that will generate crop care reminders (e.g., watering, fertilization, scouting) and deliver prioritized alerts via in-app notifications, browser push alerts, and email with quiet-hours support.
8. Conduct user acceptance testing (UAT) with local farmers, system administrators, and BSIT/agriculture students to evaluate system usability, diagnostic accuracy, and operational efficiency.

### Significance of the Project
The proposed system will provide direct practical value to the following beneficiaries:
* **Filipino Farmers and Farm Managers:** Will provide a centralized digital platform to track registered crops across growth stages, follow automated care reminders, log field observations, monitor localized weather conditions, and receive instant AI-assisted pest and disease diagnoses.
* **System Administrators:** Will provide centralized administrative controls to manage user roles, curate and update the Philippine Crop Catalog and growth stage knowledge base, and audit system activities.
* **BSIT and Agriculture Students/Researchers:** Will serve as a practical reference architecture for integrating Python/Django web engineering, relational database design, Open-Meteo meteorological APIs, and multimodal AI vision models in smart agriculture.
* **Local Farming Communities:** Will promote food security and agricultural resilience in Negros Occidental and across the Philippines by reducing crop losses caused by unmonitored diseases, pests, and severe weather hazards.

### Alignment with Institutional Research Agenda and Sustainable Development Goals
* **Institutional Research Agenda Alignment:** The proposed project will align with the Institutional IT and Agricultural Innovation Research priority of Kabankalan Catholic College, Inc. by integrating software engineering, relational data management, conversational and vision AI, and live meteorological data to modernize local agricultural workflows.
* **Sustainable Development Goal Alignment:**
  * **SDG 2 (Zero Hunger):** Will support sustainable food production and resilient farming practices in the Philippines through structured crop lifecycle tracking, early pest and disease detection, and evidence-based care recommendations (United Nations, 2015).
  * **SDG 9 (Industry, Innovation, and Infrastructure):** Will foster technological innovation in local agricultural infrastructure by introducing accessible digital farm management tools and AI-driven decision-support systems (United Nations, 2015).
  * **SDG 13 (Climate Action):** Will strengthen farmer resilience and adaptive capacity against climate-related hazards by delivering automated severe weather warnings (e.g., heavy rainfall, high winds, extreme temperatures) and actionable precautionary field guidance (United Nations, 2015).

## SCOPE AND LIMITATIONS

### System Scope & Technical Architecture
| Component | Description & Coverage |
| :--- | :--- |
| **Core Modules** | User Authentication & Role-Based Access Control (Farmer, Admin), Administrative Control Panel & Knowledge Base Curation, Agri AI Assistant Chat & Multimodal Crop Disease Diagnosis, Registered Crop Lifecycle & Growth Stage Tracking, Seasonal Crop Guidelines & Field Visual Identification Logs, Searchable Philippine Crop Catalog, Automated Farm Task & Reminder Scheduler, Agro-Meteorology (Daily Weather Records, Threshold Alerts & Forecasts), Multi-Channel Notification Center, and User Farm/AI Preferences. |
| **Technology Stack** | Web-based architecture utilizing Python (Django) for backend application logic, MySQL / Relational Database Management System (14 core entities) for structured data storage, HTML5, CSS3, JavaScript, and Bootstrap/Tailwind for front-end styling, integrated with external multimodal AI models and Open-Meteo Weather APIs. |
| **Target Users** | Local Filipino Farmers and Farm Managers (crop registration, task reminders, weather monitoring, and AI consultations) and System Administrators (user management and crop catalog curation). |

### Limitations
* Administrative and database curation rights will be restricted to authorized System Administrators; regular farmers will only access features and records permitted by their assigned user roles.
* The agro-meteorology, weather history synchronization, and automated severe weather alert modules will depend on external third-party weather data services (e.g., Open-Meteo) and will require active internet connectivity.
* AI-assisted crop disease and pest diagnosis will serve as a decision-support tool rather than a replacement for laboratory testing; diagnostic accuracy will depend on uploaded photo clarity, lighting, and visible symptoms, with complex cases requiring confirmation by an agricultural technician.
* While user preferences include a toggle for SMS notifications, active SMS gateway integration, online payment processing, e-commerce transactions, and physical IoT hardware sensor nodes will be excluded from the current development phase and may be recommended for future feature updates.
* The localized weather monitoring, geolocation defaults, and agronomic crop recommendations will be tailored specifically for Philippine geographic locations and tropical climate conditions (such as Kabankalan City and Himamaylan City in Negros Occidental).

## REFERENCES
Department of Agriculture. (2024). Climate-resilient agriculture roadmap 2024–2030. Republic of the Philippines.

Philippine Statistics Authority. (2024). Employment situation in the Philippines. Republic of the Philippines.

United Nations. (2015). Transforming our world: The 2030 Agenda for Sustainable Development. https://sdgs.un.org/2030agenda

World Bank. (2019). Climate-smart agriculture country profile: Philippines. World Bank Group. https://climateknowledgeportal.worldbank.org/


