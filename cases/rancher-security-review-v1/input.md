
# Rancher

---

Rancher 是由 Rancher Labs 开发、现隶属于 SUSE 的开源企业级 Kubernetes 多集群管理平台，核心组件以 Apache 2.0 协议开源发布。Rancher 本身不承载业务工作负载，而是作为 Kubernetes 管理平面，通过部署在下游集群中的 Agent，实现对多个 Kubernetes 集群的统一管理，并提供身份认证、权限控制、多云集群管理及应用生命周期管理等能力。由于 Rancher 掌握用户身份、集群权限、云平台凭证以及下游集群管理链路等关键资源，其安全性直接影响整个多集群管理环境。因此，本报告围绕 Rancher 的架构设计、安全机制、环境感知及典型安全漏洞展开分析，为 Rancher 安全评估与防护提供参考。

---



- [Rancher](#rancher)

  - [1. 主要功能](#1-rancher-主要功能)
  - [2. 应用案例](#2-rancher-典型应用)
    - [2.1 美国国防部 DevSecOps 平台化建设](#21-美国国防部-devsecops-平台化建设)
    - [2.2 Rancher Government Solutions 政府与军队方案](#22-rancher-government-solutions-政府与军队方案)
    - [2.3 RKE2 高安全 Kubernetes 发行版](#23-rke2-高安全-kubernetes-发行版)
    - [2.4 断连、隔离网络与战术边缘场景](#24-断连隔离网络与战术边缘场景)
  - [3. Rancher 软件架构与通信机制](#3-rancher-软件架构与通信机制)
    - [3.1 Rancher 软件架构概述](#31-rancher-软件架构概述)
    - [3.2 管理平面（Management Plane）](#32-管理平面management-plane)
      - [3.2.1 Authentication Proxy](#321-authentication-proxy)
      - [3.2.2 Rancher API Server](#322-rancher-api-server)
      - [3.2.3 Cluster Controller](#323-cluster-controller)
      - [3.2.4 Data Store（数据存储）](#324-data-store数据存储)
    - [3.3 集群通信平面（Cluster Communication Plane）](#33-集群通信平面cluster-communication-plane)
      - [3.3.1 Cluster Agent](#331-cluster-agent)
      - [3.3.2 集群通信中的身份凭证](#332-集群通信中的身份凭证)
      - [3.3.3 Reverse Tunnel](#333-reverse-tunnel)
    - [3.4 Cluster Agent 部署与接入链路](#34-cluster-agent-部署与接入链路)
      - [3.4.1 Rancher UI 侧导入操作](#341-rancher-ui-侧导入操作)
      - [3.4.2 目标集群侧 Agent 资源创建](#342-目标集群侧-agent-资源创建)
      - [3.4.3 Cluster Agent 启动与注册](#343-cluster-agent-启动与注册)
      - [3.4.4 Agent 与 Rancher Server 通信链路](#344-agent-与-rancher-server-通信链路)
  - [4. 安全机制](#4-安全机制)
    - [4.1 身份认证（Authentication）](#41-身份认证authentication)
    - [4.2 权限控制（Authorization）](#42-权限控制authorization)
    - [4.3 Agent 安全通信](#43-agent-安全通信)
    - [4.4 Token 与 Credential 安全管理](#44-token-与-credential-安全管理)
  - [5. 环境感知](#5-环境感知)
    - [5.1 网络入口感知](#51-网络入口感知)
    - [5.2 Kubernetes 资源感知](#52-kubernetes-资源感知)
    - [5.3 Agent 通信感知](#53-agent-通信感知)
    - [5.4 凭证、行为与日志审计感知](#54-凭证行为与日志审计感知)
  - [6. 典型安全漏洞分析](#6-典型安全漏洞分析)
    - [6.1 典型漏洞概览](#61-典型漏洞概览)
    - [6.2 CVE-2026-41053：GitHub App 权限映射错误](#62-cve-2026-41053github-app-权限映射错误)
    - [6.3 CVE-2026-44939：Import API 命令注入](#63-cve-2026-44939import-api-命令注入)
    - [6.4 CVE-2022-45157：vSphere 凭证暴露](#64-cve-2022-45157vsphere-凭证暴露)
    - [6.5 CVE-2024-58269：审计日志敏感信息泄露](#65-cve-2024-58269审计日志敏感信息泄露)
   

---



## 1. 主要功能

Rancher 是一个面向企业的 Kubernetes 多集群管理平台，旨在简化 Kubernetes 集群的部署、运维及管理工作，为企业提供统一的云原生管理入口。Rancher 在 Kubernetes 原有功能的基础上，提供了更加完善的集群管理、身份认证、权限控制、应用部署以及运维管理能力，其主要功能如下。

**1.1. 多kubernetes集群统一管理**：Rancher 支持统一管理多种 Kubernetes 发行版，包括 Amazon EKS、Microsoft AKS、Google GKE、阿里云 ACK、RKE2、K3s 以及符合 CNCF 标准的 Kubernetes 集群。管理员可通过统一的 Web 管理界面对多个 Kubernetes 集群进行集中管理，降低多集群环境下的运维复杂度。

**1.2. 身份认证与权限管理**：Rancher 提供完善的身份认证（Authentication）和基于角色的访问控制（Role-Based Access Control，RBAC）机制，支持本地用户、LDAP、Active Directory、GitHub、SAML、OIDC 等多种认证方式，并通过 Global Role、Cluster Role、Project Role 等权限模型，实现不同用户和团队的细粒度权限控制，提高平台安全性。

**1.3. 集群生命周期管理**：Rancher 支持 Kubernetes 集群的创建、导入、升级、扩容、节点管理及版本维护，实现集群从部署到退役的全生命周期管理。管理员可以通过图形化界面快速完成集群运维工作，提高管理效率。

**1.4. 应用部署与 Helm 管理**：Rancher 集成 Helm 应用管理功能，支持 Helm Chart 的安装、升级、回滚及卸载。用户可通过应用商店快速部署数据库、中间件、监控平台及其他云原生应用，减少应用部署的复杂度。

**1.5. GitOps 持续交付**：Rancher 集成 Fleet，实现基于 GitOps 的持续交付能力。开发人员只需将 Kubernetes 配置文件提交至 Git 仓库，Fleet 即可自动将配置同步至目标集群，实现应用的自动部署、升级及回滚，提高软件交付效率和配置一致性。

**1.6. 监控、日志与运维管理**：Rancher 提供集群监控、日志查看、事件审计、节点状态管理及资源使用情况统计等运维功能，可帮助管理员及时发现并处理集群运行过程中的异常，提高 Kubernetes 集群的稳定性和可维护性。

**1.7. 多云与混合云管理**：Rancher 支持同时管理本地数据中心和公有云中的 Kubernetes 集群，实现多云及混合云环境下的统一管理。企业无需分别登录不同云平台，即可完成 Kubernetes 集群管理、权限配置及应用部署，提高多云环境的管理效率。

---

## 2. 应用案例

## 2.1 美国国防部 DevSecOps 平台化建设
美国国防部是云原生技术在军事领域应用的典型代表。CNCF 发布的美国国防部案例中提到，DoD Enterprise DevSecOps 参考设计要求使用 CNCF 兼容的 Kubernetes 集群和开源技术，以提升软件交付速度和跨环境一致性。该案例还提到，Kubernetes 已被用于 F-16、舰船、网络攻防平台等场景，支撑军事系统的软件快速交付。
在该参考体系中，Rancher 作为 Kubernetes 多集群管理平台，与其生态中的 RKE2 等 Kubernetes 发行版共同构成可选方案，并与 OpenShift、Tanzu 等企业级 Kubernetes 平台共同支撑 DoD DevSecOps 体系建设。该案例说明，Rancher 所处的技术生态已经进入美国国防部 DevSecOps 平台化建设范围，可用于支撑多集群管理、跨环境部署和统一运维等场景。

- [Department of Defense (DoD) | CNCF](https://www.cncf.io/case-studies/dod/)（CNCF 美国国防部案例）
## 2.2 Rancher Government Solutions 政府与军队方案

<div align="center">

![Rancher Government Solutions](images/RGS.png)

<b>图 2-1 Rancher Government Solutions（RGS）政府与军队解决方案</b>

</div>

Rancher Government Solutions（RGS）是面向美国政府、军队、情报机构和民用部门提供 Rancher 相关产品与服务的组织。其官网介绍，RGS 面向美国政府和军事任务提供安全、加固、认证的开源云原生软件能力，覆盖 Kubernetes 管理、容器平台、安全合规和运维支持等方向。可以看到SUSE提供Rancher与RKE2技术能力，RGS面向美国政府与军队进行方案化交付。

RGS 还宣布其获得 DoD Enterprise Software Initiative（ESI）DevSecOps Phase II SEWP Marketplace 协议，用于加速 Kubernetes 相关能力在美国国防部体系中的采购和部署。这说明 Rancher 相关方案不仅是技术适配对象，也已经进入美国国防部软件采购与交付渠道。

- [Rancher Government Solutions（官方主页）](https://ranchergovernment.com/)
- [Rancher Government 获得 DoD Enterprise Software Initiative（ESI）协议（官方新闻）](https://ranchergovernment.com/news/rancher-government-awarded-dod-enterprise-software-initiative-agreement-accelerating-kubernetes-procurement-and-deployment)

## 2.3 RKE2 高安全 Kubernetes 发行版

RKE2（Rancher Kubernetes Engine 2）是 Rancher 推出的 Kubernetes 发行版，用于部署和运行 Kubernetes 集群，它是专门为美国联邦政府部门的安全性和合规性而设计的。与直接部署上游 Kubernetes 相比，RKE2 在保持 Kubernetes 一致性的基础上，对组件打包方式、默认安全配置及生命周期管理进行了增强，更适用于生产环境和安全要求较高的部署场景。

RKE2 面向安全加固及合规场景设计。官方文档提供 FIPS 140-2 支持说明，并配套发布 CIS Hardening Guide，用于指导 Kubernetes 集群安全加固。在政府、军队及关键基础设施等高安全场景中，RKE2 能支持满足 FIPS、CIS 等安全要求，并可结合安全基线指南进行加固，并支持 SELinux 等安全机制，因此更加适用于对安全和合规要求较高的 Kubernetes 部署环境。

- [RKE2 官方产品页面：Rancher Government Solutions](https://ranchergovernment.com/products/rke2)
- [RKE2 官方文档：FIPS Support](https://docs.rke2.io/security/fips_support)
- [RKE2 官方文档：CIS Hardening Guide](https://docs.rke2.io/security/hardening_guide)

## 2.4 断连、隔离网络与战术边缘场景

政府和军队环境常涉及断连网络、隔离网络、低带宽链路和战术边缘节点。Rancher Government 的 Hauler 用于在 air-gapped、disconnected 等受限环境中迁移容器镜像、Helm Chart 和文件，可支撑离线环境下的软件分发与部署。其 Edge Computing 方案也强调 tactical edge、远程环境和网络连接不稳定场景。
此外，Harvester Government 面向联邦和军事环境，强调 FIPS、STIG、低带宽和断连场景下的边缘基础设施能力。结合 Rancher 的多集群管理能力，上述产品与方案的有机结合可用于舰船、前沿节点、边缘机房等受限环境中的 Kubernetes 集群管理和应用交付，并适用于政府和军队常见的断连、隔离网络和高安全环境。

- [Hauler（离线软件分发）](https://ranchergovernment.com/products/hauler)
- [Edge Computing（边缘计算）](https://ranchergovernment.com/solutions/edge-computing)
- [Harvester Government（虚拟化平台）](https://ranchergovernment.com/products/harvestergovernment)

---

## 3. 软件架构与通信机制

## 3.1 Rancher 软件架构概述



Rancher 采用集中式多集群管理架构，以 **Rancher Server** 为管理中心，对多个 **Kubernetes** 集群进行统一管理。整个系统主要由 **Authentication Proxy**、**Rancher API Server**、**Cluster Controller**、**Cluster Agent**、**Kubernetes API Server** 以及 **etcd** 等组件组成。
用户通过 Rancher UI、CLI 或 API 访问 **Rancher Server**，管理请求经过身份认证和权限校验后，通过安全隧道分发至目标集群的 **Cluster Agent**，并由其与本地 **Kubernetes API Server** 交互以实现集群资源管理。

<div align="center">

![Rancher 软件架构](images/Rancher_Software_Architecture.png)

**图 3-1 Rancher 软件架构**

</div>

Rancher 软件架构可划分为两个层次：管理平面（Management Plane）、集群通信平面（Cluster Communication Plane）。两个平面共同完成用户认证、集群管理、资源调度及状态同步等工作。

## 3.2 管理平面（Management Plane）

管理平面（Management Plane）位于 Rancher 软件架构的核心位置，是整个系统的控制中心。用户发起的管理请求首先进入管理平面，由 Authentication Proxy 完成身份认证与请求代理，随后交由 Rancher API Server 结合 Rancher 权限模型进行请求处理，再由 Cluster Controller 协调对应的 Cluster Agent 将管理任务下发至下游 Kubernetes 集群，同时通过 Data Store（etcd）保存系统运行状态和配置信息。

### 3.2.1 Authentication Proxy

当用户访问 Rancher Server 时，无论请求来自 Web UI、CLI、API，还是通过 Rancher 代理的 Kubernetes API，都会首先经过 Authentication Proxy 完成身份认证。认证成功后，请求交由 Rancher API Server 处理；对于涉及下游集群资源访问的请求，再由 Cluster Controller、Cluster Agent 等组件协同完成后续处理。

Authentication Proxy 支持多种身份认证方式，包括本地用户、LDAP、Microsoft Active Directory、GitHub、OpenID Connect（OIDC）和 SAML 等。通过对接企业现有身份管理系统，Rancher 可以实现统一身份认证和单点登录，减少用户重复登录，提高平台管理效率。

Authentication Proxy 的主要职责包括：

1. 身份认证

   对访问 Rancher 平台的用户或请求进行身份验证，确认访问者身份是否合法。

2. 统一认证入口

   将来自 Web UI、CLI、API 和 kubectl 的访问请求纳入统一认证链路。

3. 请求代理与转发

   将认证后的请求交由 Rancher API Server 处理，并在访问下游集群时配合 Rancher RBAC和 Kubernetes RBAC 完成后续授权控制。

4. 身份系统集成

   支持与 LDAP、AD、OIDC、SAML 等企业身份系统集成，满足企业统一账号和权限管理需求。

在 Rancher 架构中，Authentication Proxy 位于用户访问链路的前端，是认证链路中的关键组件。

### 3.2.2 Rancher API Server

Rancher API Server 是 Rancher Server 管理平面的核心业务组件，负责接收 Authentication Proxy 完成身份认证后的请求，并对 Rancher 平台对象进行统一管理。它作为 Rancher 对外提供管理能力的统一 API 入口，负责解析用户请求、执行业务逻辑、访问数据存储，并协调 Cluster Controller、Cluster Agent 等组件完成下游 Kubernetes 集群的管理任务。

| 核心职责 | 说明 |
| -------- | ---- |
| API 入口 | 对外提供 Rancher API，接收来自 Web UI、CLI、API 等客户端的认证后请求。 |
| 业务处理 | 解析请求，处理 Cluster、Project、User、Apps 等 Rancher 平台对象的业务逻辑。 |
| 数据访问 | 读写 Rancher Data Store（如 etcd）及 Kubernetes API，维护平台配置、用户信息和集群状态。 |
| 组件协调 | 根据请求调用 Cluster Controller 等组件，并通过 Cluster Agent 协同管理目标 Kubernetes 集群。 |

从软件架构来看，Rancher API Server 位于 Rancher 管理平面的核心位置，负责统一处理认证后的管理请求，并协调 Cluster Controller、Cluster Agent 等组件完成下游 Kubernetes 集群的管理任务。它自身不负责身份认证，也不直接管理 Kubernetes 资源，而是作为各组件之间的协调中心，为 Rancher 的多集群管理提供统一的控制能力。

### 3.2.3 Cluster Controller

Cluster Controller 是 Rancher Server 管理平面中负责 Cluster 资源控制的一组控制器逻辑，主要负责监听 Cluster 对象状态变化，并协调 Rancher Server 与下游 Kubernetes 集群之间的管理流程。Authentication Proxy 完成身份认证、Rancher API Server 完成请求解析后，涉及集群管理的请求将交由 Cluster Controller 协调处理，并通过下游集群中的 Cluster Agent 完成具体的集群管理操作。

Cluster Controller 不直接访问下游 Kubernetes API，而是协调部署在下游集群中的 Cluster Agent 完成集群管理任务。对于涉及资源访问的操作，由 Cluster Agent 调用 Kubernetes API Server 执行，并将运行状态同步回 Rancher Server。

| 核心职责 | 说明 |
| -------- | ---- |
| 状态监听 | 监听 Cluster 对象状态变化，感知集群创建、导入、删除及状态更新等事件。 |
| 任务调度 | 根据 Rancher API Server 下发的管理请求，协调对应 Cluster Agent 执行集群管理操作。 |
| 状态同步 | 接收 Cluster Agent 上报的信息，更新 Rancher 中集群状态及相关运行信息。 |
| 生命周期管理 | 负责集群注册、导入、升级、删除等生命周期控制流程，并协调相关组件完成对应操作。 |

### 3.2.4 Data Store（数据存储）

Data Store 是 Rancher 管理平面的持久化存储层，用于保存平台配置、权限信息、集群元数据及运行状态等管理数据。对于多云管理场景，Cloud Credential 等云平台凭证管理信息同样属于管理平面保存的重要管理数据。在 Rancher 部署于 Kubernetes 集群时，这些管理数据统一由 Rancher API Server 通过 Kubernetes API Server 读写，并最终持久化存储于 etcd 中。Data Store 本身不参与业务处理，而是为管理平面提供统一的数据存储能力。

| 核心职责 | 说明 |
| -------- | ---- |
| 数据存储 | 保存 Rancher 管理平面的系统配置、权限信息、集群元数据及平台运行状态等管理数据。 |
| 数据持久化 | 通过 Kubernetes API Server 将管理数据持久化到 etcd，保证数据可靠保存。 |
| 数据共享 | 为 Rancher API Server、Cluster Controller 等组件提供统一的数据读取和更新能力。 |
| 状态一致性 | 保证平台配置、权限信息及集群状态的一致性，为管理平面稳定运行提供数据基础。 |

| 数据类型 | 典型内容 |
| -------- | -------- |
| 用户与认证信息 | 用户信息、认证配置、身份提供者配置等。 |
| 权限配置 | Global Role、Cluster Role、Project Role 及 RBAC 映射关系等。 |
| 集群元数据 | Cluster、Project、Node、Namespace 等管理对象及相关状态信息。 |
| 凭证管理信息 | Registration Token、API Token、Cloud Credential、TLS 证书配置、Secret 引用及相关管理信息。 |
| 系统配置 | Settings、Catalog、应用配置及平台运行参数等。 |

## 3.3 集群通信平面（Cluster Communication Plane）

集群通信平面以 Cluster Agent 为核心，通过 Token、Credential 和 Reverse Tunnel 等机制，实现 Rancher Server 与下游 Kubernetes 集群之间的安全通信。

Cluster Agent 部署于每个被 Rancher 管理的 Kubernetes 集群中，负责接收并执行Rancher Server 下发的管理任务，并同步 Kubernetes 集群运行状态，为 Rancher 实现多 Kubernetes 集群统一管理提供通信基础。

### 3.3.1 Cluster Agent

Cluster Agent（cattle-cluster-agent）是 Rancher 部署在下游 Kubernetes 集群中的核心代理组件，用于在 Rancher Server 与下游 Kubernetes 集群之间建立管理通信链路。在导入或创建下游集群时，Rancher 会通过集群注册配置或集群创建流程部署 Cluster Agent，使其运行在下游集群的 cattle-system 命名空间中，并持续与 Rancher Server 保持连接。

Cluster Agent 本身并不承载业务应用，而是作为 Rancher 在下游集群中的代理组件，负责接收并执行 Rancher Server 下发的集群管理请求，并调用 Kubernetes API Server 完成资源查询、工作负载管理、配置更新和状态同步等操作。同时，Cluster Agent 会向 Rancher Server 上报集群状态、节点信息、资源使用情况、工作负载运行状态和集群健康信息，使管理员能够在 Rancher Web UI 中统一查看和管理多个 Kubernetes 集群。

从软件架构来看，Cluster Agent 部署于下游 Kubernetes 集群中，负责连接 Rancher Server 与 Kubernetes API Server，是两者之间的通信桥梁。一方面，它通过安全通信链路与 Rancher Server 保持连接；另一方面，它依托下游集群中的 ServiceAccount 与 RBAC 权限访问 Kubernetes API，从而避免 Rancher Server 必须直接暴露或访问每个下游集群的 API Server，提升了多云、混合云和受限网络环境下的集群接入能力。

| 核心职责 | 说明 |
| -------- | ---- |
| 建立通信 | 主动与 Rancher Server 建立管理通信链路，实现 Rancher Server 与下游 Kubernetes 集群之间的管理通信。 |
| 执行管理任务 | 接收并执行 Rancher Server 下发的管理请求，并调用 Kubernetes API Server 完成资源操作。 |
| 状态同步 | 持续向 Rancher Server 同步集群、节点、工作负载及组件健康状态等运行信息。 |
| 安全通信 | 使用 ServiceAccount 身份访问 Kubernetes API Server，并通过 Reverse Tunnel 与 Rancher Server 保持安全通信。 |
### 3.3.2 集群通信中的身份凭证
Cluster Agent 与 Rancher Server 建立通信以及 Rancher 管理下游 Kubernetes 集群的过程中，需要依赖多种身份凭证完成不同阶段的认证与授权。根据使用场景的不同，这些凭证分别承担集群注册、Agent 身份认证、用户访问 Rancher API、云资源管理以及 TLS 安全通信等功能，共同构成 Rancher 集群通信过程中的身份凭证体系。

在导入已有 Kubernetes 集群时，Rancher Server 会生成包含 Cluster Registration Token 的导入清单。目标集群执行该清单后，Cluster Agent 根据其中的 Rancher Server 地址、Registration Token 及 CA 校验信息向 Rancher Server 发起注册请求。Registration Token 主要用于集群接入阶段，用于将下游集群与 Rancher 平台中的集群对象建立关联。

Cluster Agent 完成注册并进入运行阶段后，不再依赖 Registration Token，而是使用 Kubernetes 原生 ServiceAccount 及其对应的 ServiceAccount Token 作为集群内身份访问 Kubernetes API Server。Agent 能够访问哪些 Kubernetes 资源，则由对应的 RBAC 权限配置决定。与此同时，用户、CLI 或自动化程序访问 Rancher 管理接口时，通常使用 API Token 进行身份认证，该类 Token 作用于 Rancher API 访问场景，与 Cluster Agent 的注册 Token 不属于同一类凭证。

除 Cluster Agent 使用的凭证外，Rancher 在平台运行过程中还使用多种 Token 与 Credential 支撑不同功能。例如，用户、CLI 或自动化程序通常使用 API Token 调用 Rancher API；Cloud Credential 用于 Rancher 调用 AWS、Azure、GCP 等云平台接口完成集群创建或资源管理；TLS Certificate 与 Private Key 用于 Rancher Server 与 Cluster Agent 之间建立 TLS 安全通信；上述敏感配置通常由 Rancher 管理，并可能通过 Kubernetes Secret 保存或引用。

| 类型 | 主要用途 | 生命周期 / 使用阶段 |
| ---- | -------- | ------------------ |
| Cluster Registration Token | 下游 Kubernetes 集群接入 Rancher，完成 Cluster Agent 注册 | 集群注册阶段 |
| ServiceAccount Token | Cluster Agent 以 Kubernetes 原生身份访问 Kubernetes API Server | Agent 运行阶段 |
| API Token | 用户、CLI 或自动化程序访问 Rancher API | 平台管理阶段 |
| Cloud Credential | 云平台身份认证及集群创建（AWS、Azure、GCP 等） | 集群创建阶段 |
| TLS Certificate / Key | Rancher Server 与 Cluster Agent 建立 TLS 安全通信及身份校验 | 通信建立与运行阶段 |
| Kubernetes Secret | 保存 Agent 配置、证书、Token 或 Credential 引用等敏感信息 | 平台运行阶段 |


可以看出，不同类型的身份凭证分别服务于集群注册、Agent 运行、平台访问、云资源管理和安全通信等不同阶段。Rancher 并非依赖单一 Token 完成所有认证，而是根据不同业务场景采用不同类型的凭证，从而实现身份认证、访问授权和通信安全的职责分离，为后续 Reverse Tunnel 建立及多集群管理提供基础支撑。

### 3.3.3 Reverse Tunnel



### 情况一：

<div align="center">

![传统方式：Rancher Server 直接访问 Kubernetes API Server](images/rancher_tunnel_case1.png)

**图 3-5 传统方式：Rancher Server 直接访问下游 Kubernetes API Server**

</div>

针对上述问题，Rancher 采用 Cluster Agent 主动建立 Reverse Tunnel 的通信机制，以避免 Rancher Server 直接访问下游 Kubernetes API Server。

---

### 情况二：

<div align="center">

![Cluster Agent 主动建立 Reverse Tunnel](images/rancher_tunnel_case2.png)

**图 3-6 Cluster Agent 主动建立 Reverse Tunnel，Rancher Server 通过 Tunnel 间接访问下游 Kubernetes API Server**

</div>



Reverse Tunnel（反向隧道）是 Rancher Server 与下游 Kubernetes 集群之间的重要通信机制，主要用于解决 Rancher Server 难以直接访问下游 Kubernetes API Server 的场景。在直接访问模式下，管理平台需要能够连通各下游集群的 API Server，这往往要求下游集群开放管理入口，增加网络暴露面和运维复杂度。Rancher 通过部署在下游集群中的 Cluster Agent 主动向 Rancher Server 建立并维持通信连接，使管理请求可以通过该连接转发至下游集群。

Reverse Tunnel 建立后，Rancher Server 不需要直接暴露或访问下游 Kubernetes API Server，而是通过已建立的 Agent 通信通道下发管理请求。Cluster Agent 接收到请求后，再调用本地 Kubernetes API Server，完成资源查询、工作负载管理、配置更新和状态同步等操作，并将执行结果返回 Rancher Server。该机制能够适应 NAT、防火墙、私有网络和边缘环境等网络条件，提高 Rancher 在多云、混合云和受限网络场景下的部署灵活性。

从软件架构角度看，Reverse Tunnel 并不是独立运行的组件，而是 Rancher Server 与 Cluster Agent 之间的一种通信机制。它将管理平面与下游 Kubernetes 集群连接起来，在保持管理链路可达性的同时，减少下游 Kubernetes API Server 的直接暴露，是 Rancher 多集群管理架构中的关键设计。

## 3.4 Cluster Agent 部署与接入链路
Rancher 的下游集群接入，本质上是在目标 Kubernetes 集群中部署 Cluster Agent，并由 Agent 主动向 Rancher Server 建立通信连接。通过该机制，Rancher Server 不需要直接连通下游集群的 Kubernetes API Server，即可完成集群状态同步、资源查询和管理任务下发。
### 3.4.1 Rancher UI 侧导入操作
在 Rancher 中接入已有 Kubernetes 集群时，管理员首先在 Rancher Web UI 中选择导入集群。Rancher Server 会为该集群生成一段导入命令或 YAML 清单。导入命令（或其引用的 YAML）包含 Rancher Server 地址、Registration Token、CA 校验信息，以及创建 Cluster Agent 所需的 Kubernetes 资源配置。
### 3.4.2 目标集群侧 Agent 资源创建
管理员在目标 Kubernetes 集群中执行 Rancher Server 生成的导入命令后，导入命令会以 kubectl apply 的方式向目标集群创建一组 Kubernetes 资源。首先创建 cattle-system 命名空间，随后依次创建 ServiceAccount、RBAC、Secret 和 Deployment 等资源，并最终启动 cattle-cluster-agent Pod，为后续 Agent 注册和建立通信做好准备。
| Kubernetes 资源 | 在 Rancher 导入中的作用 |
| --------------- | ---------------------- |
| Namespace | 创建 cattle-system 命名空间，作为 Cluster Agent 的运行空间 |
| ServiceAccount | 为 Cluster Agent 提供访问 Kubernetes API Server 的身份 |
| RBAC（ClusterRole/ClusterRoleBinding） | 授予 Cluster Agent 所需的集群访问权限 |
| Secret | 保存 Rancher Server 地址、Registration Token、CA 校验信息等配置 |
| Deployment | 部署并管理 cattle-cluster-agent Pod |

### 3.4.3 Cluster Agent 启动与注册
<div align="center">

![Cluster Agent 导入、注册及 Reverse Tunnel 建立流程](images/rancher_cluster_agent_import_flow.png)

**图 3-7 Cluster Agent 导入、注册及 Reverse Tunnel 建立流程**

</div>
Cluster Agent Pod 启动后，会读取导入命令创建的 Secret 中保存的 Rancher Server 地址、Registration Token 和 CA 校验信息等配置。随后，Cluster Agent 主动向 Rancher Server 发起 HTTPS 连接，并完成服务器证书校验。在建立安全连接后，Cluster Agent 携带 Registration Token 发起注册认证请求。Rancher Server 校验 Token 的合法性，并将当前 Cluster Agent 与平台中的 Cluster 对象建立关联。注册成功后，目标集群状态由 Waiting 变为 Active，Cluster Agent 持续保持基于 WebSocket 的 Reverse Tunnel 长连接，为 Rancher Server 后续管理下游集群提供通信通道。

### 3.4.4 Agent 与 Rancher Server 通信链路
Cluster Agent 注册完成后，会持续与 Rancher Server 保持基于 HTTPS/WebSocket 的 Reverse Tunnel 长连接。管理员在 Rancher UI 中发起的集群管理请求不会直接访问下游 Kubernetes API Server，而是先发送至 Rancher Server，再通过 Reverse Tunnel 转发给目标集群中的 Cluster Agent，由 Agent 代表 Rancher Server 与 Kubernetes API Server 通信。

Cluster Agent 接收到 Rancher Server 转发的管理请求后，使用自身 ServiceAccount 对应的 Token 调用本地 Kubernetes API Server，完成资源查询、工作负载管理、配置变更和状态同步等操作。执行完成后，再将结果通过 Reverse Tunnel 返回 Rancher Server，并最终展示在 Rancher Web UI 中。

Cluster Agent 主动建立并保持 Reverse Tunnel 长连接，使 Rancher Server 能够通过该通道向下游集群转发管理请求，而无需直接访问 Kubernetes API Server。该设计能够较好地适应 NAT、私有网络及防火墙等网络环境，在满足网络连通性和认证条件的前提下，可实现对下游集群的统一管理，并减少 Kubernetes API Server 的直接暴露需求。

## 4. 安全机制
## 4.1 身份认证（Authentication）

在多集群管理场景中，身份认证的作用不仅是完成用户登录，更重要的是建立 Rancher 管理平台的统一身份边界。用户访问 Rancher Web UI、CLI 或 API 时，需要首先完成身份认证，认证通过后才能访问平台提供的管理功能。
从安全角度看，统一身份认证机制主要体现在三个方面：
1. 为多集群管理提供统一身份入口，减少分别维护多个 Kubernetes 集群身份认证配置的复杂度；
2. 支持与企业身份管理系统集成，便于统一实施账号生命周期管理、密码策略和多因素认证（MFA）等安全策略；
3. 为后续权限控制、审计日志和安全追踪提供统一身份标识，使平台能够对用户访问行为进行统一管理和审计。

因此，身份认证机制不仅保障了 Rancher 管理平台的访问安全，也为后续的权限控制、Agent 安全通信以及凭证管理等安全机制提供了可信的身份基础。

## 4.2 权限控制（Authorization）

Rancher 在 Kubernetes 原生 RBAC 的基础上扩展了平台级权限模型，通过 Global Role、Cluster Role 和 Project Role 实现平台、集群及项目三个层级的统一授权管理。用户完成身份认证后，Rancher 根据角色信息确定可访问范围，并将对应权限映射到 Kubernetes RBAC，由 Kubernetes API Server 对最终资源访问进行授权校验。
这里所说的"映射到 Kubernetes RBAC"，并不是将 Rancher 的角色直接复制为 Kubernetes Role，而是根据 Rancher 中定义的角色权限，在 Kubernetes 集群中创建或维护对应的 Role、ClusterRole、RoleBinding 和 ClusterRoleBinding 等 RBAC 对象，使 Kubernetes API Server 能够识别用户权限并完成授权校验。因此，Rancher 负责统一权限管理，而 Kubernetes 仍负责最终资源访问控制。

从安全角度来看，该机制将平台级授权与 Kubernetes 原生 RBAC 相结合，实现了统一授权与细粒度访问控制。一方面，管理员可以在 Rancher 中集中管理多集群用户权限，减少分别维护各 Kubernetes 集群 RBAC 配置的复杂度；另一方面，资源访问最终仍由 Kubernetes API Server 根据原生 RBAC 进行授权校验，保证权限控制能够落实到具体 Kubernetes 资源。该设计遵循最小权限原则（Least Privilege），能够降低越权访问、误操作以及权限配置不一致带来的安全风险。

其权限控制链路可以概括为：

<div align="center">

![Rancher 授权流程](images/rancher_authorization_flow.png)

**图 4-2 Rancher 授权流程**

</div>

## 4.3 Agent 安全通信
Rancher 采用 Agent 主动连接（Outbound Connection）的通信模式，由部署在下游 Kubernetes 集群中的 Cluster Agent 主动连接 Rancher Server，并与 Rancher Server 内负责集群管理的 Cluster Controller 建立通信通道。该通信过程基于 TLS 加密，并通过 CA 校验确认 Rancher Server 端证书可信，保证管理链路传输过程中的机密性和完整性。Rancher Server 无需直接暴露或主动访问下游 Kubernetes API Server，而是通过已建立的 Agent 通信通道完成后续管理请求。

从安全角度来看，该通信机制主要体现在以下三个方面：

1. 减少管理面的网络暴露

   传统集中管理平台通常需要直接访问各下游 Kubernetes API Server，而 Rancher 采用 Cluster Agent 主动发起连接的方式，使下游集群可以位于 NAT、防火墙、私有网络或边缘环境之后，无需将 Kubernetes API Server 直接暴露给 Rancher Server 或公网访问，从而降低管理链路的攻击面。

2. 保障管理链路传输安全

   Cluster Agent 与 Rancher Server 之间的通信基于 TLS 加密，并结合 CA 校验确认服务端证书可信，可降低通信过程中被窃听、篡改或中间人攻击的风险。管理请求、集群状态、事件、节点信息和健康状态等数据均通过该通信链路进行传输。

3. 约束 Agent 的集群内访问能力

   Cluster Agent 在下游集群中以 Kubernetes ServiceAccount 身份运行，其访问 Kubernetes API Server 的能力受对应 RBAC 策略约束。也就是说，Agent 对集群资源的访问并不是脱离 Kubernetes 权限体系单独存在，而是仍然落在 Kubernetes 原生身份与授权机制之内。

因此，Rancher 将 Agent 主动连接、TLS 加密通信和 Kubernetes 原生权限控制结合起来，在保证多集群统一管理能力的同时，降低了下游集群 API Server 暴露风险，并增强了管理链路的安全性。
## 4.4 Token 与 Credential 安全管理

Rancher 在集群接入、用户访问、Agent 通信以及多云资源管理过程中会使用多类 Token 与 Credential。其中，Cloud Credential 是 Rancher 多云管理场景中的关键凭证对象，用于 Rancher 调用 AWS、Azure、GCP、vSphere 等基础设施平台接口，完成集群创建、节点配置和云资源管理等操作。由于 Cloud Credential 直接关联外部云平台资源权限，一旦泄露，可能导致云主机、网络、存储或 Kubernetes 集群资源被非法创建、修改或删除，因此需要作为凭证安全管理的重点对象。
<div align="center">

![Rancher Cloud Credential 的存储与调用流程](images/rancher_cloud_credential_storage_flow.png)

</div>
从安全角度来看，Rancher 的凭证管理主要体现在以下三个方面：

1. 权限范围控制：

   不同类型的 Token 与 Credential 应仅授予完成对应任务所需的权限。Cloud Credential 尤其应遵循最小权限原则，仅授予 Rancher 创建和管理目标集群所必需的云平台权限，避免使用具有全局管理员权限的云账号。API Token 的可操作范围应受用户角色限制，Cluster Agent 使用的 ServiceAccount Token 也应受 Kubernetes RBAC 约束，从而降低越权访问风险，Registration Token 仅用于集群注册阶段，不应承担平台管理权限。

2. 生命周期管理：

  Cloud Credential 应随云账号、集群生命周期和运维职责变化进行定期检查、轮换和删除。当集群删除、云账号变更、人员离职或自动化任务废弃时，应及时撤销对应凭证，避免长期有效凭证遗留。Registration Token 主要用于集群接入阶段，完成注册后不应长期作为日常管理凭证使用；API Token 也应根据实际需要设置有效期，并按需撤销，TLS Certificate 也应根据证书生命周期及时更新或轮换。

3. 安全存储与访问控制：

  Rancher 会保存或引用 Cloud Credential、API Token、Registration Token、TLS Certificate 等凭证及敏感配置，并根据不同凭证类型以 Kubernetes Secret、Rancher 管理对象或外部凭证配置等形式保存和引用。对于 Cloud Credential，Rancher 将其作为管理对象统一管理，其敏感认证信息通常保存在 Rancher Server 所在管理集群（Local Cluster）的 Kubernetes Secret 中，并最终持久化到管理集群的 etcd 中。后续 Rancher 可通过对应的 Cloud Credential 调用云平台 API 完成集群创建和云资源管理，而无需再次手动输入认证信息。


因此，应限制普通用户、项目成员和非授权组件读取相关 Secret 或管理对象，避免因权限配置不当导致云平台凭证泄露。同时，用户访问 Rancher API、Agent 与 Rancher Server 通信以及 Rancher 调用外部云平台接口时，应通过 TLS 加密保护传输过程，降低凭证在网络中被窃听或篡改的风险。

| 凭证类型 | 主要用途 | 存储位置 | 主要风险 | 安全管理重点 |
| -------- | -------- | -------- | -------- | ------------ |
| Cloud Credential | 调用 AWS、Azure、GCP等云平台接口 | Local Cluster 的 Kubernetes Secret（最终存储于 etcd） | 云资源被非法创建、修改或删除 | 最小权限、定期轮换、保护 Secret 与 etcd |
| API Token | 用户、CLI、自动化程序访问 Rancher API | Rancher 管理对象 | 未授权调用 Rancher API | 设置有效期、按角色授权、及时撤销 |
| Registration Token | 下游集群接入 Rancher | Rancher 管理对象 / Secret | 恶意集群接入或注册关系被滥用 | 限定使用场景，接入完成后避免长期暴露 |
| ServiceAccount Token | Agent 访问下游 Kubernetes API Server | Kubernetes Secret（下游集群） | 下游集群资源被越权访问 | 受 Kubernetes RBAC 约束 |
| TLS Certificate / Key | 加密通信与证书校验 | Kubernetes Secret | 中间人攻击、通信伪造 | 证书可信、私钥保护、及时更新 |
## 5. 环境感知

Rancher 环境感知是指通过网络入口、Kubernetes 资源、Agent 通信、身份凭证、管理行为和日志审计等可观察特征，判断目标环境中是否部署 Rancher，以及 Rancher Server 与下游 Kubernetes 集群之间的管理链路是否正常。与普通 Kubernetes 运维检查不同，本章重点不在于罗列命令，而在于说明通过哪些特征可以感知 Rancher 的存在和运行状态。
## 5.1 网络入口感知
网络入口感知主要用于从外部判断目标环境是否部署 Rancher Server。Rancher Server 通常通过 HTTPS 对外提供 Web UI 和管理 API 服务，因此登录页面、TLS 证书、HTTP 响应、健康检查接口和 API 路径都可以作为感知依据。

常用验证方式如下：

```bash
# 访问 Rancher 首页，观察登录页面及 TLS 证书等特征
curl -k https://<rancher-domain>

# 访问健康检查接口，确认 Rancher Server 是否正常运行
curl -k https://<rancher-domain>/healthz

# 获取 HTTP 响应头，查看 HTTP 状态码及响应信息
curl -k -I https://<rancher-domain>
```

其中，/healthz 可作为判断 Rancher Server 健康状态的重要依据。-k 仅适用于自签名证书或内网 CA 场景下的初步探测，正式验证时仍应检查证书链。部分版本或内部通信链路中可能存在 /ping，但环境感知场景下建议优先参考官方健康检查接口 /healthz。

在授权范围内，也可以进行端口探测：

```bash
# 探测目标主机是否开放 HTTP/HTTPS 网络入口
nmap -p 80,443 <target_host>
```

部分 Docker 或自定义部署场景可能使用 8080、8443 等端口，应结合实际部署方式判断。

感知时可重点关注以下特征：

- Rancher 登录页面；
- HTTPS 服务和 TLS 证书信息；
- HTTP Header、页面标题、favicon 等 Web 特征；
- /healthz 等健康检查接口；
- Rancher Server 域名或访问入口。

需要注意的是，Rancher 生产环境通常部署在 Ingress、反向代理或负载均衡之后，外部开放端口和响应特征可能因部署方式不同而有所差异。因此，网络入口只能作为初步感知依据，仍需结合 Kubernetes 资源和 Agent 通信进一步判断。
## 5.2 Kubernetes 资源感知
获得 Kubernetes 集群访问权限后，可以通过 Kubernetes 资源判断目标集群是否受到 Rancher 管理。Rancher 相关资源通常集中部署在 cattle-system 命名空间中，但仅发现该命名空间并不能直接证明当前集群就是 Rancher 管理集群，还需要结合其中运行的组件进行综合判断。

（1）Local 集群（管理集群）： 作为 Rancher 的管理平面，通常可以看到 Rancher Server（Deployment）、rancher-webhook、Fleet Controller 等（具体组件可能因 Rancher 版本、安装方式及启用功能不同而有所差异）。



```bash
# 查看 Local 集群中的管理组件
kubectl get deploy -n cattle-system

# 查看管理组件运行状态
kubectl get pods -n cattle-system

# 查看 Rancher Server 的详细配置信息
kubectl describe deploy <rancher-deployment> -n cattle-system

# 查看 Rancher Server 日志，分析管理平面运行状态
kubectl logs -n cattle-system deploy/<rancher-deployment>
```
核心特征：若存在名为 rancher 的 Deployment、Rancher Pod 及其相关管理组件，可作为当前集群部署了 Rancher Server 的重要特征。


（2）下游受管集群（Downstream Cluster）： 通常可以看到 cattle-cluster-agent Deployment 及其 Pod。Cluster Agent 是 Rancher 在受管集群中的核心组件，也是识别 Rancher 管理关系的重要资源特征。

```bash
# 查看受管集群中的 Agent 组件
kubectl get deploy -n cattle-system

# 查看 Cluster Agent Pod 运行状态
kubectl get pods -n cattle-system

# 查看 Cluster Agent 的详细配置信息
kubectl describe deploy cattle-cluster-agent -n cattle-system
```
判定注意点：需要注意的是，Local 集群同样属于 Rancher 管理体系中的一个受管集群，因此其内部通常也会部署 cattle-cluster-agent。因此，仅凭 cattle-cluster-agent 的存在不能判断当前集群一定是导入集群或其他下游集群，还应结合是否部署了 rancher（Rancher Server）等管理组件综合分析。

根据 Rancher 的安装方式及启用功能不同，集群中还可能存在以下资源：

Fleet Controller：通常仅部署于 Local 集群；

Fleet Agent（启用后部署）：部署于所有受管集群（包括 Local 集群自身和下游集群）；

Rancher Webhook：通常命名为 rancher-webhook；

基础资源：Service、Ingress、ServiceAccount、ClusterRole、ClusterRoleBinding、Secret、ConfigMap 等 Rancher 运行相关的影子资源。

对于 Rancher 创建的下游集群（如通过 RKE/RKE2 模板创建），还可能存在 cattle-node-agent DaemonSet，用于节点级管理功能。导入型集群（Imported）通常仅以 cattle-cluster-agent 作为主要资源感知特征。
## 5.3 Agent 通信感知
在资源感知阶段，可以通过 cattle-cluster-agent 等静态资源判断集群是否受到 Rancher 管理；进一步则可通过 Agent 与 Rancher Server 的通信状态，验证该管理链路是否处于正常工作状态。Agent 通信是 Rancher 环境感知中最具代表性的动态特征之一。
对于下游 Kubernetes 集群，cattle-cluster-agent 会主动连接 Rancher Server，并通过 HTTP Upgrade 建立用于通信管理的 Reverse Tunnel（反向隧道，基于 WebSocket 协议）。在 Rancher Server 内部，该通信通常由负责集群管理的 Cluster Controller 处理。





可通过以下方式观察 Agent 状态和日志：
```bash
# 查看 Cluster Agent Pod 的运行状态
kubectl get pods -n cattle-system -l app=cattle-cluster-agent

# 查看 Cluster Agent 与 Rancher Server 的通信日志
kubectl logs -n cattle-system deployment/cattle-cluster-agent

# 若无法通过 Deployment 获取日志，可指定具体 Pod 查看
kubectl logs -n cattle-system <cluster-agent-pod-name>
```

在分析日志和配置时，可重点关注以下环境感知特征：
Server 寻址：Agent 配置（环境变量）中的 Rancher Server 地址（如 CATTLE_SERVER）；
证书校验：CA 校验信息，例如 CATTLE_CA_CHECKSUM；
身份凭证：TLS、Certificate、Authentication、Token 等身份和加密相关信息；
隧道建立：日志中建立 WebSocket / Reverse Tunnel 的连接记录（通常会请求 Rancher Server 的 /v3/connect 或 /v1/connect 路径），以及相关的 Connection、Error 或 Established 状态。

## 5.4 凭证、行为与日志审计感知

Rancher 在集群接入、用户认证、Agent 通信和云集群管理过程中会使用多种身份凭证。凭证、管理行为和日志审计信息，可以作为判断 Rancher 是否实际参与集群管理的重要辅助依据。


环境中可重点关注以下对象：


- Registration Token；
- API Token；
- ServiceAccount Token；
- Kubernetes Secret；
- Cloud Credential；
- User、Role、RoleBinding、ClusterRoleBinding；
- Cluster、Project、Namespace 等管理对象；
- Rancher Server 日志；
- Cluster Agent 日志；
- Rancher API Audit Log；
- cattle-impersonation-system 命名空间及相关资源（部分版本）。

在授权审计范围内，可结合以下方式进行验证：

```bash
kubectl get secret -n cattle-system
kubectl get serviceaccount -n cattle-system
kubectl get clusterrolebinding
kubectl logs -n cattle-system deploy/rancher
kubectl logs -n cattle-system deployment/cattle-cluster-agent
```

下游集群中还可能存在 cattle-impersonation-system 命名空间及相关 ServiceAccount、RoleBinding 等资源，可作为 Rancher 权限代理机制的辅助感知特征。

需要注意的是，API Token、Cloud Credential 等对象主要由 Rancher 管理平面维护，并不一定会以普通 Kubernetes Secret 的形式直接出现在下游集群中。其具体保存方式可能随 Rancher 版本、部署方式及凭证类型有所不同，凭证保存形式也可能存在差异。因此，凭证感知不能简单理解为“看到 Secret 就是 Rancher”，而应重点关注与 Rancher 集群接入、Agent 身份认证和云集群创建相关的凭证对象。

如果启用了 Rancher API Audit Log，还可以进一步分析用户登录、API 调用、Token 创建、权限变更、集群导入、Cluster 创建或删除、Project 配置修改等行为。管理行为和审计日志能够反映 Rancher 是否正在实际管理 Kubernetes 集群，也是安全审计的重要信息来源。

在企业多集群环境中，也可结合资产管理平台、CMDB 或自动化脚本对 Rancher 相关资源进行批量识别。自动化识别主要用于资产发现和初步筛查，最终仍需结合资源组件、Agent 通信和日志信息综合判断。



## 6. 典型安全漏洞分析
Rancher 作为企业级 Kubernetes 多集群管理平台，其安全风险主要集中在身份认证、权限映射、集群导入、多云凭证管理和审计日志等关键环节。本章选取与前文安全机制密切相关的典型 CVE 进行分析，重点说明漏洞影响对象、安全风险和修复方向，而非对全部历史漏洞进行罗列。
## 6.1 典型漏洞概览
| 漏洞编号 | 漏洞类型 | CVSS / 风险等级 | 主要影响对象 | 官方修复建议 |
|----------|----------|----------------|--------------|--------------|
| **CVE-2026-41053** | GitHub App 团队成员关系过度展开 / 权限映射错误 | **8.8 High** | 身份认证、权限映射 | 升级至 **Rancher v2.14.2** 或 **v2.13.6**；升级后执行 **Principal Refresh（用户身份刷新）**，重新同步 GitHub Team 成员关系；检查 GitHub Team 与 Rancher Role 的权限映射。 |
| **CVE-2026-44939** | Import API YAML 参数（authImage）命令注入 | **9.6 Critical** | Import API、集群导入链路 | 升级至官方修复版本；限制 Import API 使用权限；加强 Import YAML 参数校验。 |
| **CVE-2022-45157** | vSphere CPI/CSI 凭证暴露 | **9.1 Critical** | Cloud Credential、vSphere | 升级至官方修复版本；执行官方 `migrate-vsphere-clusters` 迁移脚本；限制相关 Secret 与管理对象访问权限。 |
| **CVE-2024-58269** | 审计日志敏感信息泄露 | **4.3 Medium** | Audit Log、Registration Token、Secret | 升级至 **Rancher v2.12.3**；限制审计日志访问权限；检查日志脱敏配置，避免敏感信息被记录。 |


## 6.2 CVE-2026-41053：GitHub App 权限映射错误
该漏洞存在于 GitHub App Authentication Provider 中。根据 NVD 描述，其根本原因是在 GitHub Team Membership Expansion 过程中存在 Incorrect Authentication Caching（认证缓存处理错误）。受影响版本错误扩展了用户所属 Team Membership，使用户继承了本不属于自己的 Team 对应权限，最终导致 Rancher 权限映射异常，获得超出预期的访问权限。
该漏洞说明，身份认证不仅决定用户能否登录 Rancher，还会影响后续身份映射与权限授予过程。即使 Kubernetes RBAC 本身配置没有问题，如果 Rancher 在 GitHub 身份同步或 Team Membership 映射阶段出现错误，仍可能导致用户获得超出预期的 Rancher 平台权限。
修复上应升级至 v2.13.6 或 v2.14.2，升级后 Rancher 会自动刷新受影响用户的 Principal 信息，恢复正确的 Team Membership。同时，应定期检查 GitHub Team 与 Rancher Role 的映射关系，避免身份同步异常导致权限错误。
## 6.3 CVE-2026-44939：Import API 命令注入
该漏洞存在于 Rancher 集群导入过程中 Import API（Import Endpoint）的 Import YAML 生成接口。受影响版本的 Import endpoint 对 authImage 参数校验不足，攻击者在获得有效 Cluster Registration Token 后，可能构造恶意 Import YAML URL；若诱导具有下游集群访问权限的操作者执行 kubectl apply，则可能触发命令注入风险。
该漏洞与 Cluster Agent 导入流程关系密切。Import YAML 原本用于在下游集群中部署 Agent 相关资源，一旦该入口参数校验不足，攻击面就会从“集群接入功能”扩展为“管理接口与下游集群资源创建风险”。
修复上应升级至官方修复版本，严格限制集群导入权限，保护 Registration Token，并对 Import API 访问进行审计。
## 6.4 CVE-2022-45157：vSphere 凭证暴露
该漏洞影响 Rancher 使用 vSphere 创建或管理 Kubernetes 集群的场景。受影响版本中，vSphere CPI/CSI 相关凭证可能以明文方式保存，具有相应访问权限的攻击者可能读取 vSphere 云平台认证信息。
该漏洞直接对应 Cloud Credential 安全管理问题。Cloud Credential 不只是 Rancher 内部配置，一旦泄露，攻击者可能进一步调用 vSphere API，影响虚拟机、存储、网络及 Kubernetes 集群运行环境。
修复上应升级至官方修复版本，并按照官方要求对已有 vSphere 集群执行 migrate-vsphere-clusters 迁移脚本。同时，应使用最小权限云账号，定期轮换云平台凭证，并限制管理集群中 Secret 和相关管理对象的访问权限。
## 6.5 CVE-2024-58269：审计日志敏感信息泄露
该漏洞涉及 Rancher 审计日志。受影响版本中，审计日志可能记录 secret data（敏感数据）、cluster import URLs（集群导入链接）、registration tokens（注册令牌）及相关导入命令等敏感信息。攻击者或内部用户若能够访问 Rancher 审计日志存储，可能从日志中恢复明文 Secret，获取集群导入 URL 或注册 Token，并进一步重新注册 Agent、影响下游集群或开展后续横向利用。
该漏洞说明，审计日志虽然用于安全追踪，但日志本身同样属于敏感资产。Rancher 在记录 API 请求和响应时，如果未对 Secret 注解、集群导入清单及 Registration Token 等字段进行脱敏，审计日志就可能由安全分析依据转变为敏感凭证泄露来源。
修复上应升级至 Rancher v2.12.3 或后续修复版本，并限制审计日志仅供可信人员访问。暂时无法升级时，可通过 AuditPolicy 对敏感请求和字段进行过滤与脱敏，同时定期检查日志中是否仍包含 Secret、导入 URL 或 Registration Token 等敏感内容。