HEX_COLOR_OFFSET = 0x1000000


def migrate(cr, version):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = 'pos_category'
               AND column_name = 'pos_custom_color'
        )
        """
    )
    if not cr.fetchone()[0]:
        return

    cr.execute(
        """
        SELECT id, pos_custom_color
          FROM pos_category
         WHERE pos_custom_color ~ '^#[0-9A-Fa-f]{6}$'
        """
    )
    updates = [
        (HEX_COLOR_OFFSET + int(hex_color[1:], 16), category_id)
        for category_id, hex_color in cr.fetchall()
    ]
    if updates:
        cr.executemany(
            "UPDATE pos_category SET color = %s WHERE id = %s",
            updates,
        )
