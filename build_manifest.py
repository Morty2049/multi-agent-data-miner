"""
build_manifest.py — Generate reorganize_manifest.json from Claude's analysis
of the 1,969 skill files. No LLM calls — pure static analysis.

Run: venv/bin/python build_manifest.py
Then: venv/bin/python reorganize_vault.py --apply --verify
"""
import json, os

DATA_DIR = "data"
SKILLS_DIR = "obsidian_vault/Skills"
MANIFEST_PATH = os.path.join(DATA_DIR, "reorganize_manifest.json")

# ─────────────────────────────────────────────────────────────────────────────
# 1. RENAME MAP  {current_filename_stem: canonical_name}
#    Handles: underscore→slash fixes, casing, semantic aliases, merges
# ─────────────────────────────────────────────────────────────────────────────
RENAMES = {
    # ── CI/CD ──────────────────────────────────────────────────────────────
    "CI_CD":                                    "CI/CD",
    "CI_CD pipelines":                          "CI/CD",
    "GitLab CI_CD":                             "GitLab CI/CD",
    "Continuous Integration":                   "CI/CD",

    # ── AI / ML ────────────────────────────────────────────────────────────
    "AI_LLM":                                   "AI/LLM",
    "AI_ML development":                        "AI/ML Development",
    "AI_ML security":                           "AI/ML Security",
    "AI_ML solutions":                          "AI/ML Solutions",

    # ── Specific model version artifacts (not skills) ──────────────────────
    "genai-ltst":                               "__DELETE__",
    "gpt-4o-mini-realtime-preview":             "__DELETE__",
    "text-embedding-b-large":                   "__DELETE__",
    "text-embedding-s-small":                   "__DELETE__",

    # ── Azure ──────────────────────────────────────────────────────────────
    "Azure_Arc":                                "Azure Arc",
    "Azure DevOps pipelines":                   "Azure DevOps",

    # ── Infrastructure as Code ─────────────────────────────────────────────
    "Infrastructure as Code":                   "IaC",
    "Infrastructure as Code (IaC)":             "IaC",

    # ── Kubernetes ─────────────────────────────────────────────────────────
    "Kubernetes (GKE_EKS)":                     "Kubernetes",
    "Certified Kubernetes Administrator":       "CKA",
    "Certified Kubernetes Application Developer": "CKAD",
    "EKS_ECS":                                  "__DELETE__",

    # ── Pub/Sub ────────────────────────────────────────────────────────────
    "Pub_Sub":                                  "Pub/Sub",
    "Publish_Subscribe":                        "Pub/Sub",

    # ── SSL/TLS, TCP/IP, networking ────────────────────────────────────────
    "SSL_TLS":                                  "SSL/TLS",
    "TCP_IP":                                   "TCP/IP",
    "LAN_Wi-Fi":                                "LAN/Wi-Fi",
    "Ingress_Egress":                           "Ingress/Egress",
    "Ingress_Egress Patterns":                  "Ingress/Egress Patterns",
    "CWDM_DWDM":                                "CWDM/DWDM",
    "mGRE":                                     "mGRE",

    # ── OS / IBM ───────────────────────────────────────────────────────────
    "Z_OS":                                     "z/OS",
    "Core_Banking":                             "Core Banking",
    "IBM_Qradar":                               "IBM QRadar",
    "Erlang_OTP":                               "Erlang/OTP",

    # ── Databases ──────────────────────────────────────────────────────────
    "MySQL_MariaDB":                            "MySQL",
    "PL_SQL":                                   "PL/SQL",
    "PL_pgSQL":                                 "PL/pgSQL",

    # ── Security & Compliance ──────────────────────────────────────────────
    "FCA_PRA regulations":                      "FCA/PRA Regulations",
    "GDPR_UK DPA":                              "GDPR/UK DPA",
    "ISO_IEC 27701 Auditor":                    "ISO/IEC 27701 Auditor",
    "ISO_IEC 27701 Lead Implementer":           "ISO/IEC 27701 Lead Implementer",
    "STIX_TAXII":                               "STIX/TAXII",

    # ── SAP ────────────────────────────────────────────────────────────────
    "SAP BW_4HANA":                             "SAP BW/4HANA",

    # ── Web / Frontend ─────────────────────────────────────────────────────
    "HTML_CSS":                                 "HTML/CSS",
    "UX_UI":                                    "UX/UI",
    "JavaScript frameworks_libraries":          "JavaScript Frameworks",
    "Canvas_WebGL Fingerprinting":              "Canvas/WebGL Fingerprinting",
    "Low Code_No Code":                         "Low-Code/No-Code",
    "Low Code":                                 "Low-Code/No-Code",
    "No Code":                                  "Low-Code/No-Code",

    # ── Misc / IBM file transfer ───────────────────────────────────────────
    "CFT_Connect Express":                      "CFT/Connect Express",
    "Connect_Direct":                           "Connect Direct",

    # ── Version Control ────────────────────────────────────────────────────
    "Version Control Systems":                  "Version Control",
    "Version Control Methodologies":            "Version Control",

    # ── SLA / SLO ──────────────────────────────────────────────────────────
    "SLAs":                                     "SLA",
    "SLOs":                                     "SLO",
    "SLO_SLA monitoring":                       "SLO/SLA Monitoring",

    # ── Red Hat ────────────────────────────────────────────────────────────
    "Red Hat Certified Engineer (RHCE)":        "RHCE",
    "Red Hat Certified Specialist in OpenShift Administration": "RHCA",

    # ── Custom Resource Definitions ────────────────────────────────────────
    "Custom Resource Definitions (CRDs)":       "Custom Resource Definitions",

    # ── RAG ────────────────────────────────────────────────────────────────
    "Retrieval-Augmented Generation (RAG)":     "RAG",

    # ── Group Policy ───────────────────────────────────────────────────────
    "Group Policy Object":                      "Group Policy Objects",

    # ── Kubernetes flags ───────────────────────────────────────────────────
    "Agile_Scrum":                              "Agile/Scrum",

    # ── Deployments ────────────────────────────────────────────────────────
    "deployment":                               "Deployment",
    "deployments":                              "Deployment",

    # ── Misc merges ────────────────────────────────────────────────────────
    "mParticle data pipelines":                 "mParticle",
    "pytest-docker-compose plugin":             "pytest",
    "container orchestration":                  "Container Orchestration",
    "GCP_AWS":                                  "__DELETE__",
    "Software_Hardware":                        "__DELETE__",
    "services":                                 "__DELETE__",

    # ── Casing normalizations (lowercase → Title Case) ─────────────────────
    "agent-based architectures":               "Agent-Based Architectures",
    "agentic development":                     "Agentic Development",
    "alerting":                                "Alerting",
    "audit and compliance frameworks":         "Audit and Compliance Frameworks",
    "bias mitigation":                         "Bias Mitigation",
    "biometrics":                              "Biometrics",
    "circuit breakers":                        "Circuit Breakers",
    "cloud-native traffic management":         "Cloud-Native Traffic Management",
    "compliance frameworks":                   "Compliance Frameworks",
    "container networking":                    "Container Networking",
    "cybersecurity":                           "Security",
    "data mapping":                            "Data Mapping",
    "data pipelines":                          "Data Pipelines",
    "data privacy":                            "Data Privacy",
    "developer security":                      "Developer Security",
    "encryption":                              "Encryption",
    "evaluation pipelines":                    "Evaluation Pipelines",
    "eventual consistency":                    "Eventual Consistency",
    "federation services":                     "Federation Services",
    "genAI frameworks":                        "GenAI Frameworks",
    "graph databases":                         "Graph Databases",
    "headless commerce":                       "Headless Commerce",
    "hub-spoke topologies":                    "Hub-Spoke Topologies",
    "human-in-the-loop":                       "Human-in-the-Loop",
    "idempotency":                             "Idempotency",
    "incident response":                       "Incident Response",
    "ingress":                                 "Ingress Controllers",
    "insurance systems":                       "Insurance Systems",
    "market providers":                        "__DELETE__",
    "message transformation":                  "Message Transformation",
    "model explainability":                    "Model Explainability",
    "model tampering":                         "Model Tampering",
    "multi-cloud architecture":                "Multi-Cloud Architecture",
    "namespaces":                              "Namespaces",
    "network endpoints":                       "Network Endpoints",
    "network security":                        "Network Security",
    "network segmentation":                    "Network Segmentation",
    "open banking":                            "Open Banking",
    "operators":                               "Operators",
    "peering":                                 "Peering",
    "persistent volumes":                      "Persistent Volumes",
    "pods":                                    "Pods",
    "prompt engineering":                      "Prompt Engineering",
    "prompt injection":                        "Prompt Injection",
    "recommender systems":                     "Recommender Systems",
    "reinforcement learning":                  "Reinforcement Learning",
    "route tables":                            "Route Tables",
    "routing":                                 "Routing",
    "secure storage":                          "Secure Storage",
    "semantic search":                         "Semantic Search",
    "session border controllers":              "Session Border Controllers",
    "shared flows":                            "Shared Flows",
    "statistical analysis":                    "Statistical Analysis",
    "subnets":                                 "Subnets",
    "synchronous_asynchronous patterns":       "Synchronous/Asynchronous Patterns",
    "text analytics":                          "Text Analytics",
    "topologies":                              "Topologies",
    "vulnerability management":                "Vulnerability Management",
    "workflow_model management platforms":     "Workflow/Model Management Platforms",
    "workflows":                               "Workflows",
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. CLUSTER TAGS  {canonical_name: [tags]}
#    Major skills only — the full list would be 2000 entries
# ─────────────────────────────────────────────────────────────────────────────
TAGS = {
    # Cloud platforms
    "AWS":              ["#cloud"],
    "GCP":              ["#cloud"],
    "Azure":            ["#cloud"],
    "Google Cloud":     ["#cloud"],
    "IBM Cloud":        ["#cloud"],
    "Alibaba Cloud":    ["#cloud"],
    "OVH":              ["#cloud"],
    "Scaleway Cloud":   ["#cloud"],

    # Containers & orchestration
    "Kubernetes":               ["#containers", "#devops"],
    "Docker":                   ["#containers"],
    "Docker Swarm":             ["#containers"],
    "Docker-Compose":           ["#containers"],
    "Container Orchestration":  ["#containers"],
    "Helm":                     ["#containers", "#devops"],
    "GKE":                      ["#containers", "#cloud"],
    "EKS":                      ["#containers", "#cloud"],
    "AKS":                      ["#containers", "#cloud"],
    "OpenShift":                ["#containers", "#devops"],
    "Rancher":                  ["#containers"],
    "Podman":                   ["#containers"],
    "OCI":                      ["#containers"],

    # DevOps
    "DevOps":           ["#devops"],
    "DevSecOps":        ["#devops", "#security"],
    "SRE":              ["#devops"],
    "GitOps":           ["#devops", "#ci-cd"],
    "IaC":              ["#iac", "#devops"],
    "Terraform":        ["#iac", "#devops"],
    "Ansible":          ["#iac", "#devops"],
    "Puppet":           ["#iac", "#devops"],
    "Chef":             ["#iac", "#devops"],
    "Pulumi":           ["#iac", "#devops"],
    "Crossplane":       ["#iac", "#devops"],

    # CI/CD
    "CI/CD":            ["#ci-cd", "#devops"],
    "GitHub Actions":   ["#ci-cd"],
    "GitLab CI/CD":     ["#ci-cd"],
    "Jenkins":          ["#ci-cd"],
    "ArgoCD":           ["#ci-cd", "#devops"],
    "CircleCI":         ["#ci-cd"],
    "TeamCity":         ["#ci-cd"],
    "Bamboo":           ["#ci-cd"],
    "Travis CI":        ["#ci-cd"],
    "Buildkite":        ["#ci-cd"],
    "Spinnaker":        ["#ci-cd"],
    "FluxCD":           ["#ci-cd", "#devops"],

    # Observability
    "Prometheus":       ["#observability"],
    "Grafana":          ["#observability"],
    "Datadog":          ["#observability"],
    "Splunk":           ["#observability"],
    "Dynatrace":        ["#observability"],
    "New Relic":        ["#observability"],
    "Elastic":          ["#observability"],
    "Jaeger":           ["#observability"],
    "Zipkin":           ["#observability"],
    "Loki":             ["#observability"],
    "Tempo":            ["#observability"],
    "Thanos":           ["#observability"],
    "OpenTelemetry":    ["#observability"],
    "Logging":          ["#observability"],
    "Monitoring":       ["#observability"],
    "Tracing":          ["#observability"],
    "Alerting":         ["#observability"],

    # Programming languages
    "Python":           ["#programming", "#backend"],
    "Java":             ["#programming", "#backend"],
    "JavaScript":       ["#programming", "#frontend"],
    "TypeScript":       ["#programming", "#frontend"],
    "Golang":           ["#programming", "#backend"],
    "Rust":             ["#programming", "#backend"],
    "C":                ["#programming"],
    "C++":              ["#programming"],
    "C#":               ["#programming", "#backend"],
    "Ruby":             ["#programming", "#backend"],
    "PHP":              ["#programming", "#backend"],
    "Scala":            ["#programming", "#backend"],
    "Kotlin":           ["#programming", "#mobile"],
    "Swift":            ["#programming", "#mobile"],
    "Dart":             ["#programming", "#mobile"],
    "R":                ["#programming", "#data-engineering"],
    "Perl":             ["#programming"],
    "Haskell":          ["#programming"],
    "Clojure":          ["#programming"],
    "Groovy":           ["#programming"],
    "COBOL":            ["#programming"],

    # Backend frameworks
    "FastAPI":          ["#backend"],
    "Django":           ["#backend"],
    "Flask":            ["#backend"],
    "Spring Boot":      ["#backend"],
    "Spring Framework": ["#backend"],
    "NestJS":           ["#backend"],
    "Node.js":          ["#backend"],
    "Ruby on Rails":    ["#backend"],
    "Laravel":          ["#backend"],
    "ASP.NET":          ["#backend"],
    "Gin":              ["#backend"],
    "Actix":            ["#backend"],

    # Frontend
    "React":            ["#frontend"],
    "Vue.js":           ["#frontend"],
    "Angular":          ["#frontend"],
    "Next.js":          ["#frontend"],
    "Svelte":           ["#frontend"],
    "HTML/CSS":         ["#frontend"],
    "HTML":             ["#frontend"],
    "CSS":              ["#frontend"],
    "JavaScript Frameworks": ["#frontend"],
    "Redux":            ["#frontend"],
    "Webpack":          ["#frontend"],
    "Vite":             ["#frontend"],

    # Mobile
    "React Native":     ["#mobile"],
    "Flutter":          ["#mobile"],
    "iOS":              ["#mobile"],
    "Android":          ["#mobile"],
    "Swift":            ["#mobile", "#programming"],
    "Kotlin":           ["#mobile", "#programming"],
    "Xamarin":          ["#mobile"],

    # Databases
    "PostgreSQL":       ["#databases"],
    "MySQL":            ["#databases"],
    "MongoDB":          ["#databases"],
    "Redis":            ["#databases"],
    "Elasticsearch":    ["#databases"],
    "Cassandra":        ["#databases"],
    "ClickHouse":       ["#databases"],
    "DynamoDB":         ["#databases"],
    "CosmosDB":         ["#databases"],
    "SQL Server":       ["#databases"],
    "Oracle":           ["#databases"],
    "DB2":              ["#databases"],
    "MariaDB":          ["#databases"],
    "Neo4j":            ["#databases"],
    "InfluxDB":         ["#databases"],
    "Snowflake":        ["#databases", "#data-engineering"],
    "BigQuery":         ["#databases", "#data-engineering"],
    "Databricks":       ["#databases", "#data-engineering"],

    # Data engineering
    "Apache Kafka":     ["#messaging", "#data-engineering"],
    "Kafka":            ["#messaging", "#data-engineering"],
    "Apache Spark":     ["#data-engineering"],
    "Spark":            ["#data-engineering"],
    "Apache Airflow":   ["#data-engineering"],
    "Airflow":          ["#data-engineering"],
    "dbt":              ["#data-engineering"],
    "Data Pipelines":   ["#data-engineering"],
    "ETL":              ["#data-engineering"],
    "ELT":              ["#data-engineering"],
    "Data Engineering": ["#data-engineering"],
    "Data Streaming":   ["#data-engineering"],
    "Delta Lake":       ["#data-engineering"],

    # AI/ML
    "Machine Learning": ["#ai-ml"],
    "Deep Learning":    ["#ai-ml"],
    "LLM":              ["#ai-ml"],
    "Generative AI":    ["#ai-ml"],
    "RAG":              ["#ai-ml"],
    "OpenAI":           ["#ai-ml"],
    "TensorFlow":       ["#ai-ml"],
    "PyTorch":          ["#ai-ml"],
    "LangChain":        ["#ai-ml"],
    "MLOps":            ["#ai-ml", "#devops"],
    "Prompt Engineering": ["#ai-ml"],
    "Vector Databases": ["#ai-ml", "#databases"],
    "Natural Language Processing": ["#ai-ml"],

    # Security
    "Security":         ["#security"],
    "OWASP":            ["#security"],
    "IAM":              ["#security"],
    "Zero-trust":       ["#security"],
    "PKI":              ["#security"],
    "SSL/TLS":          ["#security", "#networking"],
    "Cryptography":     ["#security"],
    "SIEM":             ["#security"],
    "Vulnerability management": ["#security"],
    "DevSecOps":        ["#security", "#devops"],

    # Messaging
    "RabbitMQ":         ["#messaging"],
    "Pub/Sub":          ["#messaging"],
    "NATS":             ["#messaging"],
    "ActiveMQ":         ["#messaging"],
    "IBM MQ":           ["#messaging"],
    "Message Queues":   ["#messaging"],

    # Networking
    "TCP/IP":           ["#networking"],
    "DNS":              ["#networking"],
    "VPN":              ["#networking"],
    "Networking":       ["#networking"],
    "BGP":              ["#networking"],
    "OSPF":             ["#networking"],
    "Load Balancing":   ["#networking"],
    "Nginx":            ["#networking", "#backend"],
    "HAProxy":          ["#networking"],

    # API
    "REST":             ["#api"],
    "REST APIs":        ["#api"],
    "GraphQL":          ["#api"],
    "gRPC":             ["#api"],
    "SOAP":             ["#api"],
    "API Gateway":      ["#api"],
    "API Design":       ["#api"],
    "API Management":   ["#api"],
    "WebSockets":       ["#api"],

    # Management
    "Agile":            ["#management"],
    "Scrum":            ["#management"],
    "Agile/Scrum":      ["#management"],
    "SAFe":             ["#management"],
    "Kanban":           ["#management"],
    "ITIL":             ["#management"],
    "Jira":             ["#management"],
    "Confluence":       ["#management"],

    # Testing
    "Selenium":         ["#testing"],
    "Playwright":       ["#testing"],
    "pytest":           ["#testing"],
    "JUnit":            ["#testing"],
    "Jest":             ["#testing"],
    "Cypress":          ["#testing"],
    "Testing Frameworks": ["#testing"],
    "Test-Driven Development": ["#testing"],

    # Certifications
    "CKA":              ["#certifications", "#containers"],
    "CKAD":             ["#certifications", "#containers"],
    "AWS Certified Solutions Architect": ["#certifications", "#cloud"],
    "CISSP":            ["#certifications", "#security"],
    "CCNA":             ["#certifications", "#networking"],
    "Terraform certification": ["#certifications", "#iac"],
}


def load_existing_skills():
    return {f[:-3] for f in os.listdir(SKILLS_DIR) if f.endswith(".md")}


def build():
    existing = load_existing_skills()
    skill_map = {}

    # ── Step 1: Apply renames ──────────────────────────────────────────────
    delete_count = rename_count = 0
    for old, canonical in RENAMES.items():
        if old not in existing:
            continue   # file doesn't exist, skip
        if canonical == "__DELETE__":
            skill_map[old] = {"canonical": "__DELETE__", "tags": []}
            delete_count += 1
        else:
            tags = TAGS.get(canonical, TAGS.get(old, []))
            skill_map[old] = {"canonical": canonical, "tags": tags}
            rename_count += 1

    # ── Step 2: Add tags for canonical skills (if not already in map) ──────
    for name, tags in TAGS.items():
        if name not in skill_map and name in existing:
            skill_map[name] = {"canonical": name, "tags": tags}

    manifest = {
        "skill_map": skill_map,
        "generated_at": "2026-04-13T00:00:00 (static analysis by Claude)",
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"✅ Manifest written: {MANIFEST_PATH}")
    print(f"   {rename_count} renames/merges")
    print(f"   {delete_count} deletions")
    print(f"   {len(TAGS)} cluster tag assignments")
    print(f"   {len(skill_map)} total entries")

    # Show renames summary
    print("\n── Top renames/merges ──────────────────────────────────────────")
    for old, entry in sorted(skill_map.items()):
        if entry["canonical"] != old and entry["canonical"] != "__DELETE__":
            print(f"  '{old}'  →  '{entry['canonical']}'")
    print("\n── Deletions ───────────────────────────────────────────────────")
    for old, entry in sorted(skill_map.items()):
        if entry["canonical"] == "__DELETE__":
            print(f"  DELETE: '{old}'")


if __name__ == "__main__":
    build()
