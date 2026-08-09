import hid
for d in hid.enumerate():
    if d["vendor_id"] == 0x19F5:
        print("VID %#06x PID %#06x usage_page %#04x usage %#04x iface %s | %s" % (
            d["vendor_id"], d["product_id"], d.get("usage_page") or 0,
            d.get("usage") or 0, d.get("interface_number"), d.get("product_string")))
