#  Pitch-A-Seat (CPBL Second-Hand Ticket Trading Platform)

##  Project Overview

**Pitch-A-Seat** is a full-featured secondary ticket trading platform for CPBL games.  
It supports ticket posting, secure payments, reservation matching, seller rating, in-site and email notifications, image uploads, and smart sorting.  
The platform also incorporates a personalized recommendation system based on multiple user behavior signals to enhance ticket discovery and user engagement.

**Website URL:** [https://pitchaseat.com](https://pitchaseat.com)

---

##  Main Features

- Post and browse second-hand tickets for CPBL games
- Secure online payments via TapPay integration
- Reservation system for upcoming games
- In-site notifications and email alerts
- Seller rating mechanism to build trust
- Personalized ticket recommendations
- Trending matches leaderboard
- Image uploads and smart ticket sorting

---

##  Technical Highlights

- **Implemented complete backend workflows for ticket trading and reservation matching**  
  Supports ticket posting, payment processing, reservation requests, seller rating, and in-site notifications. The backend is fully decoupled from the frontend to enhance scalability and maintainability.

- **Integrated third-party payment API (TapPay) for secure transactions**  
  Handled payment requests, callback validation, and transaction status updates through TapPay to ensure smooth and secure payment flows.

- **Built a personalized recommendation algorithm**  
  Designed a scoring system based on user behavior, favorite teams, and reservation history, with time-decay and normalization to mitigate outliers and handle cold-start users effectively.

- **Applied Redis caching for trending match data**  
  Cached high-traffic game information in Redis to reduce repeated database queries and improve homepage loading speed.

- **Optimized MySQL performance and ensured data integrity**  
  Created indexes on frequently queried fields and applied appropriate foreign key constraints to enhance multi-table query efficiency and maintain relational consistency.

- **Implemented JWT-based user authentication system**  
  Managed user registration, login, and access control through JWT, ensuring a simple yet secure authentication flow.

- **Developed a real-time notification system: in-site alerts and email notifications**  
  Sent transactional emails via Gmail SMTP and provided in-site alerts through a notification bell and dropdown menu, actively notifying users of important actions such as ticket updates or order changes.

- **Deployed the site with Docker and Nginx**  
  Containerized the application using Docker and set up Nginx as a reverse proxy with HTTPS encryption, deploying the site on AWS EC2 for a stable and scalable production environment.

- **Established unit tests and a CI/CD pipeline**  
  Wrote unit tests with `pytest` and used GitHub Actions to automate testing and deployment, improving code reliability and development efficiency.

- **Built cloud infrastructure with AWS services**  
  Utilized AWS RDS (MySQL) for database hosting and stored static/media assets in S3, accelerated through CloudFront for efficient content delivery.

---

##  Tech Stack

###  Backend
- Python (FastAPI, pytest)

###  Database
- MySQL

###  Cloud Services
- AWS EC2  
- AWS S3  
- AWS CloudFront  
- AWS RDS  
- AWS ElastiCache (Redis)

###  Development Tools
- Git & GitHub  
- Docker  
- Nginx  
- GitHub Actions (CI/CD)

###  Frontend
- HTML  
- CSS  
- JavaScript

---

##  System Architecture

> *(Insert architecture diagram here — recommended: PNG or SVG generated via [draw.io](https://app.diagrams.net) using AWS official icons)*

---

##  Database Schema

> *(Insert ERD or database schema diagram here — you can export from dbdiagram.io, MySQL Workbench, or draw.io)*

---
