from __future__ import annotations

import collections
import dataclasses
import datetime
import json
import pathlib

from typing import Dict, List, Optional

import click
import venmo_client as vc
import rich.table
import rich.console

console = rich.console.Console()

@dataclasses.dataclass
class Item:
  amount: float
  participants: List[Optional[str]]
  note: str

  @property
  def price_per(self):
    return round(self.amount / len(self.participants), 2)

  def charge(self, client: vc.VenmoClient, dry_run: bool = True):
    for participant in self.participants:
      if participant is ME:
        continue
      if dry_run:
        print(f"Charging {participant} ${self.price_per:.2f}:\n{self.note}")
      else:
        client.request(self.note, participant, self.price_per)

  def print_item(self):
    for participant in self.participants:
      if not participant:
        continue
      print(f'Participant: {participant}')
      print(f'Total: ${self.price_per}')
      print(self.note)
      print()
      print('------------------------')

@dataclasses.dataclass
class Receipt:
  name: str
  items: List[Item]
  total: float
  date: datetime.date

  def print_receipt(self):
    table = rich.table.Table(title=f"{self.name} - {self.date}", show_lines=True)
    table.add_column("Participants")
    table.add_column("Item")
    table.add_column("Price")
    for item in self.items:
      table.add_row(", ".join([str(p) for p in item.participants]),
                    item.note, f"${item.amount:.2f}")
    table.add_row("Subtotal", "", f"${sum([i.amount for i in self.items]):.2f}")
    table.add_row("Total", "", f"${self.total:.2f}")
    console.print(table)

  def charge(self, client: vc.VenmoClient, dry_run: bool = True):
    for item in self.items:
      item.charge(client, dry_run=dry_run)

class Me:
  def __str__(self):
    return "Me"
ME = Me()
class Everyone:
  def __str__(self):
    return "Everyone"
EVERYONE = Everyone()

def _get_participant(aliases: Dict[str, str], name: str) -> Optional[str]:
  handle = aliases.get(name, name)
  if handle == "me":
    return ME
  elif handle == "everyone":
    return EVERYONE
  return handle

def batch_receipt(receipt: Receipt, *, itemized: bool) -> Receipt:
  participants = {}
  final_charges = collections.defaultdict(list)
  subtotal = sum(c.amount for c in receipt.items)
  ratio = receipt.total / subtotal
  for item in receipt.items:
    for participant in item.participants:
      if participant not in participants:
        participants[participant] = (0., '')
      amount, notes = participants[participant]
      price_per = item.price_per * ratio
      new_note = f',{item.note}'
      new_note = f'\n${price_per:,.2f}: {item.note}'
      if (len(notes) + len(new_note) + 1) > 250:
        final_charges[participant].append((amount, notes))
        participants[participant] = (0., '')
        amount, notes = participants[participant]
      participants[participant] = (amount + price_per, notes + new_note)
  for participant, result in participants.items():
    final_charges[participant].append(result)

  if EVERYONE in final_charges:
    everyone_charge = final_charges.pop(EVERYONE)
    everyone_amount = sum([e[0] for e in everyone_charge]) / len(final_charges)
  else:
    everyone_amount = 0.
  new_items = []
  for participant, final_charges in final_charges.items():
    for amount, notes in final_charges:
      amount = amount + everyone_amount
      notes = notes + "\n" + f"${everyone_amount:.2f}: Everyone split"
      if itemized:
        notes = f"{receipt.name}\n" + notes
      else:
        notes = f"{receipt.name}"
      new_items.append(Item(amount, [participant], notes))
  return Receipt(receipt.name, new_items, receipt.total, receipt.date)

@click.command
@click.argument("receipt_file", type=click.Path(path_type=pathlib.Path))
@click.option("--execute/--dry-run", default=False)
@click.option("--print-receipt/--no-print-receipt", default=True)
@click.option("--itemized/--no-itemized", default=True)
def main(receipt_file, execute, print_receipt, itemized):
  receipt_file = receipt_file.expanduser()
  client = vc.VenmoClient(config_dir='~/.config/venmo/')
  client.authenticate()
  with open(receipt_file, 'r') as fp:
    receipt = json.load(fp)

  date = datetime.datetime.strptime(receipt["date"], "%Y-%m-%d").date()
  aliases = receipt["aliases"]

  items = []
  for item in receipt["items"]:
    name, participants, cost = item
    handles = [_get_participant(aliases, p) for p in participants]
    items.append(Item(cost, handles, name))
  receipt = Receipt(receipt["name"], items, receipt["total"], date)
  if print_receipt:
    receipt.print_receipt()
  receipt = batch_receipt(receipt, itemized=itemized)
  if print_receipt:
    receipt.print_receipt()
  receipt.charge(client, dry_run=not execute)

if __name__ == "__main__":
  main()
