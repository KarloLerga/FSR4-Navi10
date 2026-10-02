# FSR4-Navi10 Codex Pack

Ovaj paket je pripremljen za jedan dugi lokalni Codex run na Windows računalu s RX 5700 XT / Navi10.

## Cilj
Napraviti kvalitetom što vjerniju FSR 4.0.2 izvedbu za Navi10, s punim FP16 backendom kao primarnim putem, ali bez dogmatskog forsiranja sporije matematike. Ako neki originalni INT8 pass na stvarnom gfx1010 ispadne brži i daje isti rezultat, završni autotuner ga smije zadržati samo za taj pass. Glavni cilj je najbolji konačni quality/performance rezultat na RX 5700 XT.

## Što ti radiš
1. Raspakiraj ovaj ZIP u kratku putanju, preporuka: `C:\Dev\FSR4-Navi10`.
2. Otvori taj folder u VS Codeu.
3. Pokreni Codex lokalno u tom workspaceu, s najvišim reasoningom koji ti je dostupan.
4. Omogući mu pisanje u workspace, terminal i internet.
5. Zalijepi sadržaj `CODEX_START_PROMPT.txt`.
6. Ako Windows prikaže UAC prompt za instalaciju Build Toolsa, potvrdi ga.

Nemoj ručno instalirati ostale dependencyje prije toga osim ako ih već imaš. `scripts/bootstrap.ps1` je namjerno napisan tako da Codex odradi većinu instalacije i preuzimanja sam.

## Što Codex mora završiti
- automatski bootstrap toolchaina
- dohvat i zaključavanje upstream sourceova
- standalone FSR4 test/harness aplikaciju
- referentni originalni FSR4 path
- potpuni FP16 neural path za Navi10
- high-precision FP16 path
- per-pass hybrid/autotuning path
- offline konverziju i prepacking weightova
- specijalizirane HLSL shadere za svaki FSR4 pass/preset/tier
- DirectX 12 runtime
- FSR API compatibility adapter
- shader compilation/cache/pipeline cache
- numeričku, temporalnu i performance validaciju
- release bundle i dokumentirani rezultat

## Važno
Paket NE sadrži AMD-ov FSR4 source ili model assete. Codex ih treba dohvatiti iz upstreama tijekom rada, u skladu s `docs/UPSTREAMS_AND_LICENSE.md`. Time ZIP ostaje mali, čist i bez redistribucije third-party koda.

## Prvo što Codex mora pročitati
- `AGENTS.md`
- `.agent/PLANS.md`
- `docs/MASTER_SPEC.md`
- `docs/DECISIONS.md`
- `docs/UPSTREAMS_AND_LICENSE.md`
- `docs/NAVI10_BACKEND.md`
- `docs/NUMERICS_AND_QUALITY.md`
- `docs/ACCEPTANCE_CRITERIA.md`

## Dodatne zaštite za dugi run
Codex mora prije završetka proći `docs/CODE_REVIEW_CHECKLIST.md`. Ako zapne na očekivanom problemu (fetch, DXC/gfx1010 instrukcija, FP16 divergence, RGA/RGP, reboot, GPU crash), `docs/FAILURE_MODES.md` definira kako se treba oporaviti bez odustajanja od cijelog projekta.
