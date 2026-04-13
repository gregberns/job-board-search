# Batch 05: Rust & Systems-Language Companies

*Research date: 2026-04-10*
*Focus: Companies using Rust (and a few C#) in production, filtered through the four-filter flywheel*
*Excluded: Modal, Foxglove, Anduril, Nominal (already evaluated)*

---

## Rust Job Boards & Communities

Before the company reviews, here's where to find Rust jobs:

**Dedicated Rust Job Boards:**
- **RustJobs.dev** — Exclusive Rust listings, no recruiters/aggregators. Browse free, join talent network for matching. https://rustjobs.dev
- **Rust.Careers** — Community-driven Rust job board with thousands of listings. https://rust.careers
- **Let's Get Rusty Jobs** — Curated Rust positions. https://jobs.letsgetrusty.com
- **ReadyToTouch** — Weekly-updated list of ~300 product companies using Rust in production (2026 edition). https://users.rust-lang.org/t/job-focused-list-of-product-companies-using-rust-in-production-2026-readytotouch/138847

**HN Who is Hiring (Rust-filtered):**
- https://hnhiring.com/technologies/rust — Filters every monthly HN thread for Rust mentions
- April 2026 thread: https://news.ycombinator.com/item?id=47601859

**Community Channels:**
- Rust Programming Language Community Discord: https://discord.com/invite/rust-lang-community (~general, with job-adjacent channels)
- Rust Zulip (official): https://rust-lang.zulipchat.com — where Rust teams coordinate
- r/rust on Reddit — job posts appear periodically
- GitHub: https://github.com/omarabid/rust-companies — maintained list of companies using Rust in production

**General boards with Rust filters:**
- Wellfound (AngelList): https://wellfound.com/role/rust-developer
- Arc.dev: https://arc.dev/remote-jobs/rust
- Built In: https://builtin.com/companies/tech/rust-companies

---

## RUST COMPANIES

---

## 1. Monumental
**Domain:** Autonomous construction robotics
**What:** Builds autonomous ground vehicles that lay bricks and construct masonry walls on real construction sites. Their robots have built facades for houses, canal retaining walls, and office buildings across the Netherlands. Think software-defined construction — not augmenting human bricklayers, replacing the manual process entirely with robots that navigate, position, and build autonomously.
**Why Rust:** Each AGV runs control and navigation logic written entirely in Rust. Their construction OS "Atrium" is built with TypeScript and Rust, with Rust compiled to WebAssembly so the UI interfaces directly with the same control code deployed to robots. Also C++ and Python in the stack.
**Flywheel:**
1. Dead inside? No — construction productivity has declined for decades. Autonomous construction is consequential.
2. Hard, important problem? Yes — robots that navigate unpredictable construction sites, handle real-world tolerances, and build structural walls autonomously.
3. Software/AI is the product AND the lever? Yes — Atrium turns construction into a software problem. Remove the autonomy stack and you have expensive hardware that can't build.
4. Outsized impact? Yes — each site deployment generates data that improves autonomy. More deployments = better robots = more building types = compounds.
**Size:** ~100 employees. Team from Palantir, Qualcomm, Dyson, Tesla, Meta, 1X.
**Stack:** Rust, C++, Python, TypeScript, WebAssembly
**ATS:** Direct apply (monumental.co/jobs)
**Remote:** No — 5 days/week onsite in Amsterdam. Visa sponsorship available.
**Career URL:** https://www.monumental.co/jobs

**Your take:**
> 

---

## 2. Scythe Robotics
**Domain:** Autonomous commercial landscaping
**What:** Self-driving, all-electric mowers for commercial landscape maintenance. Not consumer lawnmowers — industrial-scale autonomous machines that operate in complex outdoor environments. Eliminates emissions and reduces labor dependency for a $100B+ industry.
**Why Rust:** Made a principled decision 4+ years ago to write ALL on-robot software in Rust. Lonely choice at the time, has paid huge dividends. Every perception, autonomy, and control system runs Rust. No previous robotics experience required for their Rust roles — they want great Rust engineers and teach the robotics.
**Flywheel:**
1. Dead inside? Moderate — landscape maintenance isn't glamorous, but electrifying and automating outdoor work at scale has real environmental impact.
2. Hard, important problem? Yes — autonomous navigation in unstructured outdoor environments (slopes, obstacles, wet grass, property boundaries) is genuinely hard.
3. Software/AI is the lever? Yes — the robot is hardware, but the autonomy stack is what makes it work. Remove the software and you have an expensive electric mower that can't drive itself.
4. Outsized impact? Somewhat — more deployments = more training data = better autonomy. But the compounding is more linear than exponential. Each new mower type is incremental.
**Size:** Series B ($97M total). ~80-105 employees. Expanding to 394 jobs in Colorado.
**Stack:** Rust (primary on-robot), perception and autonomy systems
**ATS:** Lever (`scytherobotics`)
**Remote:** Hybrid — Boulder/Longmont CO, Austin TX, Vero Beach FL, and remote.
**Career URL:** https://scytherobotics.com/careers

**Your take:**
> 

---

## 3. K2 Space
**Domain:** Large satellite manufacturing
**What:** Building the largest and highest-power satellites ever flown. Thesis: Falcon 9 and Starship enable mass abundance in orbit, but spacecraft design hasn't caught up. K2 designs satellites that fully utilize massive launch vehicles — 20kW+ power, unprecedented payload capacity. $450M raised, $500M+ in signed contracts across commercial and US government.
**Why Rust:** Software team builds their stack primarily in Rust "because modern programming languages should be fun, as well as correct." GNC algorithms (Rust, C++), flight computer applications (Rust, C++), embedded microcontroller software (Rust, C++), operating systems (Rust, C++, C), test systems (Python). Rust is the primary language, not a secondary.
**Flywheel:**
1. Dead inside? No — building the infrastructure layer of space is fundamental. These satellites enable everything from communications to Earth observation.
2. Hard, important problem? Yes — real-time, fault-tolerant control systems for 20kW+ spacecraft. Propulsion, guidance, communications — all mission-critical.
3. Software/AI is the lever? Partially — software is critical but this is ultimately a hardware company. The satellites are the product, software enables them.
4. Outsized impact? Yes — production-line satellite manufacturing compounds. Each satellite design iteration improves the platform for all customers.
**Size:** $450M raised. ~284 employees. Backed by leading investors.
**Stack:** Rust (primary), C++, C, Python, VHDL, SystemVerilog
**ATS:** Greenhouse (`k2spacecorporation`)
**Remote:** Hybrid — some positions remote in US.
**Career URL:** https://www.k2space.com/careers

**Your take:**
> 

---

## 4. Relativity Space
**Domain:** 3D-printed rockets + autonomous manufacturing
**What:** Vertically integrated platform fusing 3D printing, AI, and autonomous robotics to manufacture rockets with 100x fewer parts in under 60 days. Not just building rockets — building the factory of the future. Their Stargate printer is the world's largest metal 3D printer.
**Why Rust:** Flight software engineers must be "experts in Rust, C++, and/or other system languages." Staff Robotics Software Engineer requires 5+ years in C/C++ and/or Rust. The Integrated Software team controls rockets from launch pad to orbit and creates the autonomous manufacturing systems.
**Flywheel:**
1. Dead inside? No — manufacturing rockets with 100x fewer parts through autonomous robotics is transformative.
2. Hard, important problem? Yes — real-time control from launch to orbit, plus autonomous manufacturing that eliminates most traditional rocket assembly.
3. Software/AI is the lever? Yes — the autonomous factory IS software. Remove AI and you can't 3D-print rockets. The Stargate printer is a software-controlled manufacturing platform.
4. Outsized impact? Yes — every print run trains the AI. Simpler supply chain + software iteration = faster improvement cycles. Compounds across rocket programs.
**Size:** ~182 open jobs. LA headquarters. Well-funded (multiple rounds).
**Stack:** Rust, C++, Python, Docker. Flight + manufacturing software.
**ATS:** Greenhouse (`Relativity`)
**Remote:** Mostly onsite in Long Beach, CA.
**Career URL:** https://www.relativityspace.com/careers

**Your take:**
> 

---

## 5. Applied Intuition
**Domain:** Autonomous vehicle simulation and development platform
**What:** Software infrastructure to develop, test, and deploy autonomous vehicles at scale. Creates digital proving grounds with high-fidelity 3D worlds and physics-based sensor models. 18 of top 20 global automakers and major DoD programs are customers. Valued at $15B.
**Why Rust:** Autonomy Engineer positions require proficiency in Rust and C++. The simulation and testing infrastructure demands the performance and correctness guarantees Rust provides for physics simulation and sensor modeling.
**Flywheel:**
1. Dead inside? No — enabling safe autonomous vehicles is consequential. Every car company and defense program needs this.
2. Hard, important problem? Yes — physics-based simulation that accurately predicts real-world autonomous vehicle behavior is extremely hard.
3. Software/AI is the product AND the lever? Yes — pure software platform. Remove it and every AV program needs to build their own testing infrastructure.
4. Outsized impact? Yes — every customer deployment adds scenario data. Platform improvements benefit all customers. More vehicle types = more sensor models = compounds.
**Size:** Series F, $15B valuation. 1,000+ engineers. 40+ ex-CTOs, 30+ former founders.
**Stack:** Rust, C++, simulation engines, 3D rendering, physics
**ATS:** Greenhouse (`appliedintuition`)
**Remote:** Mostly onsite — Mountain View CA, plus offices in DC, San Diego, Ann Arbor, Munich, Stockholm, others.
**Career URL:** https://www.appliedintuition.com/careers

**Your take:**
> 

---

## 6. Cognite
**Domain:** Industrial digital twin / DataOps platform
**What:** SaaS platform (Cognite Data Fusion) that contextualizes OT/IT data for heavy-asset industries — oil and gas, power and utilities, manufacturing, shipping. Creates digital twins that enable real-time monitoring, simulation, and optimization across entire industrial operations. 700+ employees worldwide.
**Why Rust:** Actively hiring Senior Software Engineers (Rust/Kotlin) for critical authentication and authorization services on the platform. Also hires C#/.NET engineers for ETL tools that onboard data from industrial sources (SAP, OPC-UA, PI). Both Rust AND C# in the stack — unusual and interesting.
**Flywheel:**
1. Dead inside? Yes — industrial DataOps is important but it's fundamentally a data plumbing problem. Making existing operations more efficient, not enabling what wasn't possible before.
2. Hard, important problem? Moderate — contextualizing messy industrial data is hard, but it's an efficiency play, not a new capability.
3. Software/AI is the lever? Yes — CDF is the product. Without it, industrial data stays siloed.
4. Outsized impact? Moderate — platform effects exist but compounding is limited. Each customer deployment is somewhat bespoke.
**Size:** $225M raised, Series B. ~700 employees. Oslo, Austin, Houston, Tokyo.
**Stack:** Rust, Kotlin, C#/.NET, Python
**ATS:** Lever (`cognite`)
**Remote:** Hybrid — some US positions (Houston, Austin, others). Rust/Kotlin role is Oslo-based.
**Career URL:** https://www.cognite.com/en/company/careers

**Your take:**
> 

---

## 7. Parallel Systems
**Domain:** Autonomous electric freight rail
**What:** Battery-powered autonomous railcars that can platoon together or split off to different destinations en route. Hauls standard shipping containers up to 500 miles on a single charge. Founded by ex-SpaceX engineers. Makes rail economical for short-distance freight that currently goes on trucks.
**Why Rust:** Technology stack built using Rust. Control systems, navigation, and autonomy for rail vehicles where safety and performance are non-negotiable.
**Flywheel:**
1. Dead inside? No — shifting freight from trucks to rail is a massive decarbonization lever with real economic impact.
2. Hard, important problem? Yes — autonomous rail vehicles that platoon, split, and navigate existing rail infrastructure safely.
3. Software/AI is the lever? Yes — the autonomy and coordination software is what makes individual railcars economically viable. Without it, you just have electric railcars that need human operators.
4. Outsized impact? Yes — each route adds operational data. More routes = better autonomy = more freight shifted from trucks. Network effects compound.
**Size:** $100M+ raised. LA-based. Commercial launch targeting 2026.
**Stack:** Rust, autonomous systems, embedded
**ATS:** Unknown — apply via moveparallel.com
**Remote:** Likely onsite in LA.
**Career URL:** https://www.moveparallel.com/

**Your take:**
> 

---

## 8. Oxide Computer
**Domain:** Integrated on-premises cloud infrastructure (hardware + software)
**What:** Rethinking the server rack by designing hardware and software together from the ground up — their own compute sleds, switches, firmware, hypervisor, and control plane. For organizations that need cloud-like infrastructure on-prem (finance, energy, manufacturing, government). Everything is open source.
**Why Rust:** The entire software stack is written in Rust and C. Host OS (Helios), hypervisor (Propolis), block storage (Crucible), embedded OS (Hubris), control plane (Omicron) — all Rust. This is one of the most Rust-intensive companies in existence.
**Flywheel:**
1. Dead inside? Moderate — on-prem cloud infrastructure is important but it's infrastructure. It enables other things rather than being the thing itself.
2. Hard, important problem? Yes — building an entire computer from firmware to control plane is genuinely hard. But it's infrastructure, not applied to a physical-world problem.
3. Software/AI is the lever? Partially — the integration of hardware and software IS the product. But it's infrastructure serving other companies' workloads.
4. Outsized impact? Moderate — platform improvements benefit all deployments, but this is fundamentally a hardware product with software. Growth is linear (sell more racks).
**Size:** $370M raised (Series B). Remote team. Everyone makes $250K regardless of location.
**Stack:** Rust (primary), C. Open source everything.
**ATS:** Direct apply (oxide.computer/careers)
**Remote:** Yes — remote-friendly, overlap with Pacific Time for 4+ hours.
**Career URL:** https://oxide.computer/careers

**Your take:**
> 

---

## 9. Rerun
**Domain:** Multimodal data visualization for robotics and spatial AI
**What:** Open-source SDK for logging, storing, querying, and visualizing multimodal data from robots, drones, autonomous vehicles, and spatial AI systems. The debugging and understanding layer for physical AI. Used across robotics, generative media, industrial processing, simulation, and health.
**Why Rust:** Built entirely in Rust using egui (CTO Emil Ernerfeldt created egui, the biggest open-source GUI framework in Rust). The platform is Rust-native from the ground up.
**Flywheel:**
1. Dead inside? Moderate — visualization tooling is important but it's a devtools play. Enables other companies to build physical AI, not building it directly.
2. Hard, important problem? Yes — visualizing multimodal, multi-rate robotics data in real-time is technically hard. But it's tooling, not the end application.
3. Software/AI is the lever? Yes — pure software product. Visualization infrastructure for the physical AI stack.
4. Outsized impact? Moderate — open-source community effects. But devtools revenue scales more linearly than platform effects.
**Size:** Seed ($20.2M total). <10 employees. Stockholm-based, remote-first.
**Stack:** Rust (100%), egui
**ATS:** Direct apply (careers.rerun.io)
**Remote:** Yes — distributed, remote-first. Synchronous hours 13-17 CET.
**Career URL:** https://careers.rerun.io

**Your take:**
> 

---

## 10. Hadean
**Domain:** Distributed computing platform for simulation and digital twins
**What:** AI-powered spatial computing platform for decision support and digital twin simulation. Customers include UK Ministry of Defence, BAE Systems, Deloitte, Microsoft. Delivers industrial and defense simulations at scale — highway digital twins, battle simulations, large-scale spatial computing.
**Why Rust:** Platform SDK built entirely in Rust. Engineers lean on the compiler for correctness in distributed simulation scenarios where trust in the simulation is critical. Rapid iteration is easier in Rust because the compiler catches errors that would be runtime failures in other languages.
**Flywheel:**
1. Dead inside? Moderate — simulation and digital twins are interesting but the applications are varied (defense, highways, enterprise). Not a single hard problem.
2. Hard, important problem? Yes — distributed spatial computing at scale for real-time simulation is technically hard.
3. Software/AI is the lever? Yes — pure platform play. The computing substrate enables simulations that weren't feasible before.
4. Outsized impact? Moderate — platform improvements benefit all customers, but deployment is somewhat bespoke per use case.
**Size:** $65.9M raised. ~68-79 employees. London HQ. Investors include Epic Games, Tencent, In-Q-Tel, Ericsson.
**Stack:** Rust (platform SDK), C++ (customer-facing)
**ATS:** TeamTailor (hadean.teamtailor.com)
**Remote:** London-based, some remote. Primarily UK/Europe.
**Career URL:** https://hadean.com/careers/

**Your take:**
> 

---

## 11. Gecko Robotics
**Domain:** Industrial infrastructure inspection
**What:** Already reviewed in Batch 02, but worth noting here for the Rust angle. Wall-climbing robots + AI platform for inspecting power plants, refineries, pipelines. What wasn't captured before: **Rust is part of their embedded systems stack** alongside C/C++ and Python. They use Cargo for dependency management alongside Pip and Conan.
**Why Rust:** Used for embedded systems and infrastructure-level work on the robots themselves. Python/React/TypeScript for the data platform and full-stack.
**Note:** See Batch 02 entry for full review. User said "Quite cool. A lot of similarities to what Cognite is doing. Challenge is it looks like its on-site on the east coast US."
**Stack update:** Python, C++, **Rust**, Verilog/HDL (embedded), React/TypeScript (platform)
**ATS:** Ashby (`gecko-robotics`)
**Career URL:** https://www.geckorobotics.com/careers

---

## 12. Tangram Vision
**Domain:** Perception calibration for robotics and autonomy
**What:** Calibration software and services for robots, drones, and autonomous systems. Makes it easy to build safe, reliable autonomous products that scale. Won NASA Phase II SBIR for operator-free multi-modal calibration on the lunar surface (AutoCal). Industry veterans who've shipped multiple robotics platforms.
**Why Rust:** Full Rust shop. Large codebase written in Rust. They were early advocates for "Rust for Robotics" and wrote influential blog posts about it. Believe Rust is the best language for full-stack robotics and perception development.
**Flywheel:**
1. Dead inside? Moderate — calibration is critical infrastructure for autonomy, but it's a niche enabling technology, not the end product.
2. Hard, important problem? Yes — multi-sensor calibration that works reliably at scale is genuinely hard and under-solved.
3. Software/AI is the lever? Yes — pure software. Remove calibration tools and every robotics company has to solve this themselves (badly).
4. Outsized impact? Limited — calibration is important but narrow. Market size is bounded by robotics adoption.
**Size:** Seed ($1.5M). Small team of industry veterans. NASA customer.
**Stack:** Rust (primary)
**ATS:** Direct apply (tangramvision.com/careers)
**Remote:** Fully remote. Company retreats every 3-4 months. Tulsa, OK HQ (nominal).
**Career URL:** https://www.tangramvision.com/careers

**Your take:**
> 

---

## 13. Quilter
**Domain:** AI-driven PCB layout from physics first principles
**What:** Uses reinforcement learning and physics simulation to autonomously lay out printed circuit boards. Built from scratch — custom CAD kernels, high-fidelity physics engines, and RL agents that design boards directly from electromagnetic, thermodynamic, and signal propagation evaluations. Founded by ex-SpaceX engineer. Claims designs that "surpass what any human has created."
**Why Rust:** Not confirmed, but their stack is built from first principles including low-level CAD kernels and physics engines — exactly the kind of systems work where Rust shines. Worth investigating.
**Flywheel:**
1. Dead inside? Yes — PCB layout is essential to every piece of hardware, and autonomous design from physics is genuinely novel.
2. Hard, important problem? Yes — replacing human PCB designers with RL agents that understand electromagnetics is extremely hard.
3. Software/AI is the product AND the lever? Yes — the AI IS the product. Remove it and you have no company. Every board designed generates training data.
4. Outsized impact? Yes — every PCB designed by the AI improves the model. More board types = more physics scenarios = better designs. Hardware design velocity compounds.
**Size:** Series B ($25M, total ~$35M). Benchmark, Index Ventures. Founded by ex-SpaceX.
**Stack:** Custom CAD kernels, physics engines, RL agents. Languages TBD — likely C++/Rust/Python.
**ATS:** Direct apply (quilter.ai/careers)
**Remote:** Unknown — investigate.
**Career URL:** https://www.quilter.ai/careers

**Your take:**
> 

---

## 14. Path Robotics
**Domain:** AI-powered autonomous welding
**What:** Builds "Physical AI" for manufacturing. Intelligent welding cells that see, think, and adapt — combining computer vision, ML, and real-time control. Their foundational AI model "Obsidian" is trained on tens of millions of welded inches. Addresses a 600K welder shortage projected by 2030. Each cell delivers production-quality welds without programming.
**Why Rust:** Not confirmed for Rust specifically, but their stack includes C++ and C# for robotics and full-stack applications. Worth investigating for systems-language roles.
**Flywheel:**
1. Dead inside? No — solving the skilled welder shortage through AI is consequential. Manufacturing can't scale without welding.
2. Hard, important problem? Yes — real-time adaptive welding that handles variation in parts, materials, and joint geometry. Obsidian is a foundational AI model for a physical process.
3. Software/AI is the product AND the lever? Yes — Obsidian IS the product. Remove the AI and you have a standard robot arm that can't weld without human programming.
4. Outsized impact? Yes — every welded inch trains Obsidian. More installations = more data = better welds across all customers. Foundational model compounds.
**Size:** $271M raised, Series D. ~198 employees. Columbus, OH.
**Stack:** C++, C#, React, Node.js, computer vision, ML
**ATS:** Greenhouse (`pathrobotics`)
**Remote:** Mostly onsite in Columbus, OH.
**Career URL:** https://www.path-robotics.com/careers

**Your take:**
> 

---

## 15. Machina Labs
**Domain:** AI-robotic sheet metal forming (software-defined manufacturing)
**What:** Operates "elastic factories" where AI-guided robotic arms incrementally form sheet metal into complex structures directly from CAD — like an experienced craftsman with a hammer, but at industrial scale and precision. Eliminates multi-million-dollar dies and stamping machines. Customers include Lockheed Martin and Toyota. Building a 200,000 sq ft factory with ~50 robots.
**Why Rust:** Not confirmed for Rust. Stack includes TypeScript, Python, Docker, Kubernetes. But the real-time robotic control and AI-driven forming is the kind of systems work where Rust could appear. Worth watching.
**Flywheel:**
1. Dead inside? No — eliminating tooling-specific dies from metal forming is transformative. Any shape from any CAD file, on demand.
2. Hard, important problem? Yes — real-time AI-guided robotic forming that achieves aerospace-grade precision from sensor feedback alone.
3. Software/AI is the product AND the lever? Yes — the AI controls the forming process. Remove it and robots can't form parts. Every formed part generates training data.
4. Outsized impact? Yes — every part trains the AI. More geometries = better forming models = more industries served. Software-defined manufacturing compounds.
**Size:** $124M+ raised. ~100+ employees. Chatsworth, CA (LA area). Backed by Lockheed Martin, Toyota, NVIDIA.
**Stack:** TypeScript, Python, Docker, Kubernetes, Azure/AWS, robotic control systems
**ATS:** Lever (`MachinaLabs`)
**Remote:** Mostly onsite in Chatsworth, CA.
**Career URL:** https://machinalabs.ai/careers

**Your take:**
> 

---

## 16. Bright Machines
**Domain:** Software-defined manufacturing (microfactories)
**What:** Full-stack solution for automated assembly across the manufacturing lifecycle — from product design to assembly to disassembly. Their "microfactories" use computer vision, ML, and software-controlled robotic assembly cells. Customers span consumer electronics, automotive, and industrial manufacturing. Making assembly lines reconfigurable through software rather than physical retooling.
**Why Rust:** Not confirmed. Software-defined manufacturing platform likely involves systems-level programming. Worth investigating.
**Flywheel:**
1. Dead inside? Moderate — reconfigurable assembly is important but it's an efficiency improvement to existing manufacturing processes.
2. Hard, important problem? Yes — general-purpose robotic assembly that handles multiple product types without retooling is hard.
3. Software/AI is the lever? Yes — the software makes hardware reconfigurable. Without it, each assembly line is purpose-built.
4. Outsized impact? Moderate — platform improvements help all deployments, but each customer installation is somewhat bespoke.
**Size:** $390M raised, Series C. ~239 employees across 5 continents. Backed by BlackRock, NVIDIA, Microsoft, Eclipse.
**Stack:** Computer vision, ML, robotic control, cloud platform
**ATS:** Lever (`brightmachines`)
**Remote:** Distributed across 5 continents — likely remote-friendly.
**Career URL:** https://www.brightmachines.com/careers/

**Your take:**
> 

---

## C# COMPANIES

These are C# shops that might pass the four filters. The bar is high — C# needs to be in service of a hard, consequential problem where the software is the lever, not backoffice tooling.

---

## 17. Symbotic (C#/.NET)
**Domain:** AI-powered warehouse automation
**What:** Fully automated, end-to-end supply chain solutions for the world's largest retailers and wholesalers. Autonomous robot fleets orchestrated by intelligent software within high-density warehouse structures. Faster throughput, maximized storage, precise order accuracy. Public company (NASDAQ: SYM), $2.39B revenue, $6.27B market cap.
**Why C#:** C#/.NET is used for their warehouse control systems. Evolving monolithic systems toward microservices (.NET Core, Kubernetes, RabbitMQ, Redis). Also uses C++ for robotics.
**Flywheel:**
1. Dead inside? Moderate — warehouse automation is important but it's efficiency optimization, not enabling what wasn't possible before. Warehouses existed before Symbotic.
2. Hard, important problem? Yes — orchestrating autonomous robot fleets in dense warehouse environments with real-time coordination is technically hard.
3. Software/AI is the lever? Yes — the software orchestrates the robots. Without it, you have expensive hardware that can't coordinate.
4. Outsized impact? Moderate — platform improvements help, but each installation is a large custom deployment. Growth is linear (sign more retailers).
**Size:** Public company. ~1,887 employees. Wilmington, MA.
**Stack:** C#/.NET, C++, microservices, Kubernetes, RabbitMQ, Redis
**ATS:** Direct apply (symbotic.com/careers)
**Remote:** Mostly onsite in Wilmington, MA.
**Career URL:** https://www.symbotic.com/careers/

**Your take:**
> 

---

## 18. Path Robotics (C# — also listed above)
**Domain:** AI-powered autonomous welding
**Note:** Already listed as #14 above. Included here because their full-stack applications use C# alongside React and Node.js. The C# is in service of a genuinely hard physical-world problem (foundational AI for welding), not backoffice tooling. This is exactly the kind of C# company that could pass all four filters.
**Career URL:** https://www.path-robotics.com/careers

---

## 19. Cognite (C# — also listed above)
**Domain:** Industrial digital twin / DataOps
**Note:** Already listed as #6 above. Included here because they hire C#/.NET engineers for ETL tools connecting industrial data sources. The C# is in service of industrial operations (oil/gas, utilities, manufacturing), but the work itself is data plumbing — connecting SAP, OPC-UA, PI systems. Yellow flag territory: the C# work might be the backoffice integration layer rather than the core product.
**Career URL:** https://www.cognite.com/en/company/careers

---

## HONORABLE MENTIONS (Interesting but didn't fully pass filters)

**Kyber (France)** — Remote control SDK for machines (robots, drones, desktops) with ultra-low latency video. Built on FFmpeg/VLC. Interesting tech but tiny ($3.97M raised) and unclear product-market fit. https://kyberlabs.ai

**Estuary** — Real-time data replication in Rust and Go. Interesting Rust company but it's data infrastructure (devtools), not a physical-world problem. $24M raised. https://estuary.dev

**Dioxus Labs** — Cross-platform GUI framework for Rust (web, desktop, mobile). YC-backed, tiny team, hiring first full-time Rust engineer in SF. Pure devtools. https://dioxuslabs.com

**Viam** — Robotics software platform (Go/Python primary, not Rust). Founded by MongoDB co-founder. Makes robotics programmable. Interesting but it's a platform, and Go-primary. https://www.viam.com

**Parsec Automation (C#)** — TrakSYS MES platform used in 11,000+ plants across 140 countries. Manufacturing operations management. C#/SQL. But it's MES/backoffice optimization — exactly the kind of C# shop that's a yellow flag. https://parsec-corp.com
