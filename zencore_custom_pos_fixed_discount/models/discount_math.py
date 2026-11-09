"""Currency-unit allocation mirrored by static/src/js/discount_math.js."""
from decimal import Decimal, ROUND_HALF_UP


def allocate_discount(grosses, discount_type, value, rounding):
    quantum = Decimal(str(rounding))

    def units(amount):
        return int((Decimal(str(amount)) / quantum).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    weights = [max(0, units(gross)) for gross in grosses]
    base = sum(weights)
    value = max(Decimal('0'), Decimal(str(value)))
    if discount_type == 'percent':
        target = int((Decimal(base) * min(value, Decimal('100')) / 100).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP))
    elif discount_type == 'fixed':
        target = min(base, units(value))
    else:
        target = 0
    if not base or not target:
        return [0.0] * len(weights)
    allocations = [target * weight // base for weight in weights]
    ranking = sorted(range(len(weights)), key=lambda i: (-(target * weights[i] % base), i))
    for index in ranking[:target - sum(allocations)]:
        allocations[index] += 1
    return [float(quantum * amount) for amount in allocations]


def refund_share(amount, source_qty, returned_qty, previous_qty, round_amount):
    if not source_qty:
        return 0.0
    before = min(abs(source_qty), max(0, previous_qty))
    after = min(abs(source_qty), before + abs(returned_qty))
    return round_amount(round_amount(amount * after / abs(source_qty)) -
                        round_amount(amount * before / abs(source_qty)))
