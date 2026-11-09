import { ColorList } from "@web/core/colorlist/colorlist";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

const HEX_COLOR_OFFSET = 0x1000000;
const PALETTE_COLORS = Array.from({ length: 12 }, (_, color) => color);

export class PosCategoryHexColorField extends Component {
    static template = "north_end_pos_inline_config.PosCategoryHexColorField";
    static components = { ColorList };
    static props = { ...standardFieldProps };

    get value() {
        return Number(this.props.record.data[this.props.name] || 0);
    }

    get selectedPaletteColor() {
        return this.value < 12 ? this.value : undefined;
    }

    get colors() {
        return PALETTE_COLORS;
    }

    get hexColor() {
        if (this.value < HEX_COLOR_OFFSET || this.value > HEX_COLOR_OFFSET + 0xffffff) {
            return "";
        }
        return `#${(this.value - HEX_COLOR_OFFSET).toString(16).padStart(6, "0")}`;
    }

    get pickerColor() {
        return this.hexColor || "#ffffff";
    }

    get customColorStyle() {
        return this.hexColor ? `background-color: ${this.hexColor};` : "";
    }

    onPaletteColorSelected(color) {
        this.props.record.update({ [this.props.name]: color });
    }

    onHexPickerChange(event) {
        this.setHexColor(event.target.value);
    }

    onHexTextChange(event) {
        const entered = event.target.value.trim();
        if (!entered) {
            this.props.record.update({ [this.props.name]: 0 });
            return;
        }
        const hex = entered.startsWith("#") ? entered : `#${entered}`;
        if (!/^#[0-9a-f]{6}$/i.test(hex)) {
            event.target.setCustomValidity("Enter a six-digit HEX color, for example #7A3E48.");
            event.target.reportValidity();
            return;
        }
        event.target.setCustomValidity("");
        this.setHexColor(hex);
    }

    setHexColor(hex) {
        if (!/^#[0-9a-f]{6}$/i.test(hex)) {
            return;
        }
        this.props.record.update({
            [this.props.name]: HEX_COLOR_OFFSET + Number.parseInt(hex.slice(1), 16),
        });
    }
}

registry.category("fields").add("pos_category_hex_color", {
    component: PosCategoryHexColorField,
    supportedTypes: ["integer"],
});
