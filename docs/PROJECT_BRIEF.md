# Project Brief

## Project name

ISAAC1

## Purpose

ISAAC1 will provide an internet-accessible control system for a Teltonika RUT241 connected to a Tonmind SIP-T21 paging adapter.

## What problem this project solves

ISAAC1 will let an authorised user switch Tonmind SIP-T21 relay outputs on and off over the internet, with the RUT241 acting as the LTE gateway and remote software update point.

## Intended users

- Operators who need remote relay control.
- Installers configuring the RUT241 and SIP-T21 in the field.
- Developers maintaining ISAAC1 software remotely.

## Initial assumptions

- The project will remain separate from all OneSchool code and data.
- Requirements will be clarified before building major features.
- Private, sensitive, or environment-specific data will not be committed.
- The first deployment path uses Ethernet setup to bootstrap secure remote access to the RUT241.
- Remote RUT241 access should use Teltonika RMS or a VPN tunnel rather than exposing SSH/WebUI directly to the internet.
- The SIP-T21 relay API must be confirmed from Tonmind documentation before relay-control code is written.

## Open questions

- Which remote management path will be used first: Teltonika RMS, WireGuard/OpenVPN, or another tunnel?
- What are the exact SIP-T21 HTTP endpoints and authentication rules for relay on/off control?
- What SIM provider/APN will be used, and does it provide a public IP or CGNAT?
- What user authentication should protect the ISAAC1 relay-control interface?

## Decisions log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-06-27 | Created initial development workspace. | Prepare a clean project before defining requirements. |
| 2026-06-27 | Defined ISAAC1 target architecture around RUT241 remote access and SIP-T21 relay control. | Establish the first field setup milestone before building the relay UI. |
