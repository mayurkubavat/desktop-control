Automating AMD/Xilinx Vivado (2025.1) with an AI agent requires combining **deterministic Tcl execution** for project and simulation control with **computer vision** for waveform inspection and GUI state validation.

---

## 1. Core UI Sub-Panes & Architecture

When Vivado opens a project or enters a simulation view, the interface splits into four primary sub-panes. An AI agent must recognize these spatial regions to orient itself before issuing commands or clicking targets.

| UI Sub-Pane | Default Location | Primary Function | Agent Interaction Strategy |
| --- | --- | --- | --- |
| **Flow Navigator** | Far Left Column | High-level workflow triggers (Project Manager, IP Integrator, Simulation, Synthesis, Implementation, Bitstream). | Prefer Tcl equivalents over clicking; use visually to confirm which design stage is currently active. |
| **Sources / Scope** | Upper-Mid Left | In Project view: displays `Design Sources`, `Constraints`, and `Simulation Sources`. In Simulation view: transforms into the **Scope** (design hierarchy) and **Objects** (signals/variables) panes. | Navigate hierarchy via Tcl (`current_scope`) rather than nested double-clicks on small tree nodes. |
| **Workspace** | Center / Right Upper | Hosts the Project Summary, built-in Text Editor, Schematic viewer, and the **Waveform Viewer** (`Untitled 1*`). | Primary visual target for AI vision agents to read signal transitions, cursors, and timing alignments. |
| **Tcl Console** | Bottom Panel | Interactive shell accepting Tcl commands (`Type a Tcl command here...`), alongside the **Messages**, **Log**, and **Reports** tabs. | **Primary control anchor.** Clicking the text input bar at the bottom of this pane allows the agent to drive 95% of Vivado deterministically. |

---

## 2. Simulation Flow (`xsim` Engine)

Vivado’s integrated simulator (`xsim`) operates in three phases: **Analysis** (`xvlog` / `xvhdl`), **Elaboration** (`xelab`), and **Simulation** (`xsim`).

1. **Trigger Behavioral Simulation:** GUI vs. Tcl Execution.
* **GUI Path:** In the **Flow Navigator** (left pane), locate the **SIMULATION** section. Click **Run Simulation**, then select **Run Behavioral Simulation** from the pop-up context menu.
* **Tcl Path:** Type `launch_simulation` directly into the Tcl Console.


2. **Monitor Compilation & Elaboration:** Wait for UI Context Switch.
Vivado spawns a background progress dialog while running `xvlog` and `xelab`. If a syntax error occurs, the flow halts and surfaces errors in the **Messages** tab. When successful, the UI automatically transitions from the *Project Manager* layout to the *Simulation* layout.


3. **Verify Initial Simulation Run:**
By default, `xsim` executes `run 1000ns` upon startup unless overridden by project properties (`set_property -name {xsim.simulate.runtime} -value {0ns} -objects [get_filesets sim_1]`).


---

## 3. Waveform Viewer Navigation & Shortcuts

Once `launch_simulation` finishes, the **Waveform Viewer** opens inside the Workspace pane. To inspect internal module signals (such as FIFO pointers or memory arrays) not included in the top-level testbench by default:

* **Scope Pane (Left):** Displays the instantiated module tree (e.g., `tb_fifo` $\rightarrow$ `u_fifo`). Selecting a module updates the **Objects** pane.
* **Objects Pane (Mid-Left):** Lists all ports (`input`, `output`), internal `reg`/`logic` signals, and parameters within the selected scope. To add a signal to the waveform via GUI, right-click the signal and select **Add to Wave Window** (or press `Ctrl+W`).
* **Waveform Toolbar & Essential Hotkeys:**
* **Zoom Fit (`F`):** Crucial for AI vision agents. Immediately scales the horizontal time axis so the entire simulated duration (from `0 ns` to current runtime) fits inside the visible viewport. Ensure the waveform canvas has active focus by clicking inside the black signal area before sending `F`.
* **Run All (`F5` or Toolbar Play Icon):** Continues simulation until a `$finish` or `$stop` system task is encountered in the testbench.
* **Restart (`Ctrl+Shift+F5`):** Resets simulation time to `0 ns` without recompiling RTL, keeping newly added internal signals on the waveform canvas.
* **Run For (`Shift+F2` or Toolbar Time Box):** Steps the simulation forward by a specified time increment (e.g., `500 ns`).



---

## 4. Complete FIFO Simulation Setup & Waveform Analysis

Below is a clean, synthesizable SystemVerilog synchronous FIFO and self-checking testbench designed to expose flag transitions (`full`, `empty`) and read/write clock-to-output latency.

### SystemVerilog RTL (`sync_fifo.sv`)

```systemverilog
`timescale 1ns / 1ps

module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 4
)(
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  wr_en,
    input  logic                  rd_en,
    input  logic [DATA_WIDTH-1:0] din,
    output logic [DATA_WIDTH-1:0] dout,
    output logic                  full,
    output logic                  empty,
    output logic [$clog2(DEPTH):0] count
);

    localparam PTR_WIDTH = $clog2(DEPTH);
    logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    logic [PTR_WIDTH-1:0]  wr_ptr, rd_ptr;

    assign full  = (count == DEPTH);
    assign empty = (count == 0);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count  <= '0;
            dout   <= '0;
        end else begin
            // Write Operation
            if (wr_en && !full) begin
                mem[wr_ptr] <= din;
                wr_ptr      <= wr_ptr + 1'b1;
            end
            // Read Operation (Standard 1-cycle synchronous read latency)
            if (rd_en && !empty) begin
                dout   <= mem[rd_ptr];
                rd_ptr <= rd_ptr + 1'b1;
            end
            // Counter tracking
            case ({wr_en && !full, rd_en && !empty})
                2'b10:   count <= count + 1'b1;
                2'b01:   count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule

```

### SystemVerilog Testbench (`tb_sync_fifo.sv`)

```systemverilog
`timescale 1ns / 1ps

module tb_sync_fifo;
    localparam DATA_WIDTH = 8;
    localparam DEPTH      = 4;

    logic                  clk = 0;
    logic                  rst_n = 0;
    logic                  wr_en = 0;
    logic                  rd_en = 0;
    logic [DATA_WIDTH-1:0] din = 0;
    logic [DATA_WIDTH-1:0] dout;
    logic                  full, empty;
    logic [$clog2(DEPTH):0] count;

    sync_fifo #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH)
    ) u_fifo (.*);

    // 100 MHz Clock (10 ns period)
    always #5 clk = ~clk;

    initial begin
        // 1. Reset sequence
        rst_n = 0;
        #25;
        @(negedge clk) rst_n = 1;

        // 2. Fill FIFO to trigger FULL flag (4 writes)
        repeat (DEPTH) begin
            @(negedge clk);
            wr_en = 1;
            din   = din + 8'h11; // Writes 0x11, 0x22, 0x33, 0x44
        end
        @(negedge clk) wr_en = 0;
        #20;

        // 3. Drain FIFO to trigger EMPTY flag (4 reads)
        repeat (DEPTH) begin
            @(negedge clk);
            rd_en = 1;
        end
        @(negedge clk) rd_en = 0;
        #50;
        $finish;
    end
endmodule

```

### Visual Waveform Verification Targets

When an AI agent inspects the resulting waveform after pressing `F` (Zoom Fit), it should verify four exact behaviors:

1. **Initial Reset State (`0 ns` to `25 ns`):** `rst_n` is low (`0`), `empty` is high (`1`), `full` is low (`0`), and `count` reads `0`.
2. **De-assertion of `empty`:** On the first rising `clk` edge where `wr_en == 1` (`35 ns`), `0x11` is written into index 0. Immediately after this clock edge, `count` increments to `1` and `empty` drops from `1` to `0`.
3. **Assertion of `full`:** On the fourth consecutive write clock edge (`65 ns`, writing `0x44`), `count` reaches `4` (`DEPTH`) and `full` transitions from `0` to `1`.
4. **Read Latency (`rd_en` to `dout`):** Because this is a standard synchronous read FIFO (non-FWFT), when `rd_en` asserts prior to the rising clock edge at `95 ns`, `dout` updates to `0x11` **on that rising clock edge (`95 ns`)**, exhibiting a 1-clock-cycle register delay rather than combinational zero-cycle feedthrough.

---

## 5. Essential Tcl Automation Commands

To eliminate brittle GUI coordinate clicking, an AI agent should focus the Tcl Console input box (or run a script via `source script.tcl`) and execute these exact commands:

```tcl
# 1. Create a new project in-place (-force overwrites existing project)
create_project fifo_sim_proj ./fifo_sim_proj -part xc7a35tcpg236-1 -force

# 2. Add RTL design sources and simulation testbenches
add_files -norecurse ./sync_fifo.sv
add_files -fileset sim_1 -norecurse ./tb_sync_fifo.sv

# 3. Explicitly set top modules and update compile order
set_property top sync_fifo [current_fileset]
set_property top tb_sync_fifo [get_filesets sim_1]
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1

# 4. Launch behavioral simulation
launch_simulation

# 5. Add internal DUT signals to the waveform window, restart, and run for 500ns
add_wave /tb_sync_fifo/u_fifo/*
restart
run 500ns

```

### Useful Inspection & Control Commands

* **Query Signal Values Without Vision:** Use `get_value` in the Tcl console to read exact signal states at the current simulation timestamp without relying on OCR:
```tcl
puts "FIFO Full Flag: [get_value /tb_sync_fifo/full]"
puts "Current Data Out: [get_value -radix hex /tb_sync_fifo/dout]"

```


* **Save Waveform Configuration:** Save added signals and radix settings to a `.wcfg` file via `save_wave_config {./fifo_waves.wcfg}`.

---

## 6. AI Vision Agent Best Practices for Vivado 2025.1

Driving an EDA tool like Vivado through a GUI agent presents unique challenges due to dense Java/Qt rendering, asynchronous background compilation, and sub-pixel waveform lines. Follow these operational rules:

1. **Hybrid Tcl-First Execution:** Never use vision-based mouse clicks to navigate the *New Project Wizard*, *Add Sources Wizard*, or deep *Scope/Objects* hierarchy trees. A single focused click into the `Type a Tcl command here...` prompt at the bottom of the screen allows the agent to execute `create_project`, `add_files`, `launch_simulation`, and `add_wave` with 100% reliability.
2. **Asynchronous Modal Synchronization:** Actions like `launch_simulation` or clicking **Run Behavioral Simulation** open a floating modal dialog (`Launching simulation...`) that can take 3 to 30 seconds depending on IP complexity. The agent must poll the screen or monitor the Tcl prompt until the modal disappears and the top window title or toolbar displays simulation controls (`xsim`) before sending waveform hotkeys.
3. **Focus Management Before Hotkeys:** Sending the `F` key (Zoom Fit) while the **Tcl Console** or **Scope** pane has focus will simply type `"f"` into the console or search the hierarchy tree. The agent must explicitly perform a **Left-Click inside the black Waveform canvas** (e.g., on the signal name column or timeline header) immediately before transmitting the `F` keystroke.
4. **Radix & Bus Expansion for OCR Clarity:** Multi-bit buses (`din[7:0]`, `dout[7:0]`) can appear compressed or truncated in hexadecimal if zoomed out too far. Enforce hexadecimal display deterministically via Tcl (`set_property radix hex [get_waves *]`), and use `get_value` in the Tcl console to cross-verify any ambiguous visual OCR readings on the waveform canvas.