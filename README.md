# HQ DFM

<p>
    English |<a href="README_CN.md">中文<a/>
</p>

### Implementing One-Click PCB Design Flaw Analysis with HQ DFM in KiCad

The HQ DFM plugin will assist you in:

- One-click analysis of over 20 design risk issues including open circuits, disconnected traces, line spacing, and width.
- Automatically analyzing PCB design flaws and eliminating production difficulties and design defects.

After checking the design flaws, you can use the NextPCB plugin to directly add them to your shopping cart at Huaqiu.
![HQDFM Plugin](dfm-screen.gif)

## Features

### Design Parameter Analysis

HQ DFM will analyze the following parameters in your KiCad design:

- Layer Count
- Dimensions
- Signal Integrity
- Smallest Trace Width
- Smallest Trace Spacing
- Pad size
- Pad Spacing
- Hatched Copper Pour
- Hole Diameter
- RingHole
- Drill Hole Spacing
- Drill to Copper
- Board Edge Clearance
- Special Drill Holes
- Holes on SMD Pads
- Missing SMask Openings
- Drill Hole Density
- Surface Finish Area
- Test Point Count

## Installation

Install the latest release plugin from **Plugin and Content Manager**. Open the "Plugin and Content Manager" from the main window, Navigate to the "Plugins" section and locate "HQ DFM" in the list. Finally, Click on the "Install" button and "Apply Pending Changes" to finalize the installation process.
![image](kicad_dfm/picture/HQDFM.png)

### About HQ DFM

[HQ DFM](https://dfm.hqpcb.com/) is an efficient PCB design software that performs one-click analysis of design risks, provides optimization solutions, and generates Gerber, BOM, and coordinate files, making design and manufacturing simpler.

you can use the HQDFM Gerber Viewer to double check your manufacturing files, adjust board parameters then add it to your NextPCB cart directly.

### About HQ PCB / NextPCB

HQ PCB specializes in reliable multilayer PCB manufacture and assembly, and like KiCad, our goal is to enable engineers to build tomorrow's electronics. NextPCB is working with KiCad to provide smart tools to simplify the progression from design to physical product. With 3 major factories catering to prototyping, mass production and PCB assembly, and over 15 years of engineering expertise, NextPCB believes our industrial experience will prove invaluable to KiCad users and the PCB design community.

We are a [KiCad Platinum Sponsor](https://www.nextpcb.com/blog/kicad-nextpcb-platinum-sponsorship).



### kicad-HQ install

## Windows

The Windows installation package can be downloaded directly using the following link:
https://www.eda.cn/data/kicad-release/kicad-huaqiu-8.0.6-x86_64.exe.zip

## Linux
The Linux version requires Flatpak installation

# 1，Install flatpak

`sudo apt install flatpak`

# 2，Map a domain name to a specific IP address

`sudo vim /etc/hosts`

Use vim to go to etc/host and add this line：
`175.6.14.183 kicad.huaqiu.com`

Check whether the connection is successful:
`ping kicad.huaqiu.com`

# 3，Add a remote kicad repository

`flatpak remote-add --user repo https://kicad.huaqiu.com/kicadhuaqiu`

Check whether the addition succeeds：
`flatpak remote-ls repo`

If GPG verification is reported, go to Step 4. Otherwise, skip it

# 4，Ignore package unsigned authentication and modify the configuration with the vim editor

`vim ~/.local/share/flatpak/repo/config`

Modify in the file:
`gpg-verify=false`

`flatpak remote-modify --no-gpg-verify repo`

Check whether the addition is successful:
`flatpak remote-ls repo`

# 5，Install kicad

`flatpak install repo org.kicad.KiCad`

If no dependency is reported, go to the next step "6".

# 6，Lack of SDK dependency, use domestic flathub mirror warehouse, add remote warehouse first, and then install the missing dependency:

`sudo flatpak remote-modify flathub --url=https://mirror.sjtu.edu.cn/flathub`

In case of lack org.freedesktop.Sdk/x86_64/23.08：
`flatpak install flathub org.freedesktop.Sdk/x86_64/23.08`

In case of lack org.freedesktop.Sdk//23.08：
`flatpak install flathub org.freedesktop.Sdk//23.08`
