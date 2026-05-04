# Vendored PicoRV32

Source: https://github.com/YosysHQ/picorv32
Pinned commit: `87c89acc18994c8cf9a2311e871818e87d304568` (HEAD as of 2026-05-03)
License: ISC (see `LICENSE`)

This directory contains a single file from upstream:

- `picorv32.v` — the unmodified PicoRV32 source. Contains all upstream
  modules including:
  - `picorv32` — the RV32I core
  - `picorv32_regs` — the register file
  - `picorv32_pcpi_*` — PCPI mul/fast_mul/div coprocessors (unused, parameter-disabled)
  - `picorv32_axi` / `picorv32_axi_adapter` — AXI master wrappers (unused)
  - `picorv32_wb` — Wishbone B4 master wrapper (this is what `rtl/soc/picorv32_wrapper.v` instantiates)

We use `picorv32_wb` directly: it exposes the WB-master signal names
(`wbm_cyc_o`/`wbm_stb_o`/`wbm_we_o`/`wbm_sel_o`/`wbm_adr_o`/`wbm_dat_o`/
`wbm_dat_i`/`wbm_ack_i`) that match our `wb_interconnect` master port.

The only adaptation done in `rtl/soc/picorv32_wrapper.v` is converting our
active-low `rst_n` to upstream's active-high `wb_rst_i` (one inverter),
and tying off PCPI/IRQ/trace ports that we do not consume. No upstream
modification.

## Updating

To re-vendor at a new commit:

```
cd /tmp && git clone https://github.com/YosysHQ/picorv32 picorv32-clone
cp picorv32-clone/picorv32.v <repo>/vendor/picorv32/picorv32.v
cp picorv32-clone/COPYING    <repo>/vendor/picorv32/LICENSE
# update SHA above
```

Do not edit `picorv32.v` in place. If a behavior change is needed, do it in
`rtl/soc/picorv32_wrapper.v`.
